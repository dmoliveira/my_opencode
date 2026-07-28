export type SecretRedactionErrorCode =
  | "invalid_pattern"
  | "immutable_match"
  | "cycle_detected"
  | "depth_limit"
  | "node_limit"
  | "text_limit"
  | "malformed_provider_metadata"
  | "mutation_failed"
  | "unexpected_failure"

export type SecretRedactionMatchTarget = "key" | "value"

export type SecretRedactionLocationCode =
  | "provider_metadata_openai_item_id"
  | "provider_metadata_openai_other"
  | "immutable_protocol_field"
  | "unknown_field"

interface SecretRedactionMatchDiagnostics {
  matchTarget: SecretRedactionMatchTarget
  patternIndex: number
  locationCode: SecretRedactionLocationCode
}

export class SecretRedactionError extends Error {
  readonly code: SecretRedactionErrorCode
  readonly matchTarget: SecretRedactionMatchTarget | null
  readonly patternIndex: number | null
  readonly locationCode: SecretRedactionLocationCode | null

  constructor(
    code: SecretRedactionErrorCode,
    detail = "",
    diagnostics: SecretRedactionMatchDiagnostics | null = null,
  ) {
    super(`secret redaction blocked: ${code}${detail ? ` (${detail})` : ""}`)
    this.name = "SecretRedactionError"
    this.code = code
    this.matchTarget = diagnostics?.matchTarget ?? null
    this.patternIndex = diagnostics?.patternIndex ?? null
    this.locationCode = diagnostics?.locationCode ?? null
  }
}

export interface SecretRedactionLimits {
  maxDepth: number
  maxNodes: number
  maxChars: number
}

export interface ProviderSecretRedactionLimits {
  maxMessages: number
  maxNodes: number
  maxChars: number
  maxMessageChars: number
}

export interface SecretRedactionStats {
  matches: number
  redactedFields: number
  scannedChars: number
  scannedNodes: number
}

interface CompiledPattern {
  source: string
  flags: string
}

interface PatternApplication {
  text: string
  firstPatternIndex: number | null
}

type VisitMode = "redact" | "scan"
type PropertyPath = Array<string | number>

interface ResourceBudget {
  nodes: number
  chars: number
  maxNodes: number
  maxChars: number
}

interface TraversalState {
  stats: SecretRedactionStats
  budget: ResourceBudget
  maxDepth: number
  active: WeakSet<object>
  visited: WeakSet<object>
  revisitAliases: boolean
}

type ToolStateMetadataProjection =
  | { kind: "skip" }
  | { kind: "output"; value: string }
  | null

const MISSING_OWN_VALUE = Symbol("missing-own-value")

const MUTABLE_CONTENT_KEYS = new Set([
  "after",
  "before",
  "body",
  "content",
  "description",
  "diff",
  "diffs",
  "error",
  "input",
  "message",
  "output",
  "prompt",
  "reasoning",
  "source",
  "summary",
  "system",
  "text",
  "title",
])

const IMMUTABLE_PROTOCOL_KEYS = new Set([
  "callID",
  "filename",
  "id",
  "messageID",
  "metadata",
  "mime",
  "modelID",
  "path",
  "providerID",
  "role",
  "sessionID",
  "tool",
  "type",
  "url",
])

function normalizedLimit(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback
}

function ownDataValue(
  value: unknown,
  key: PropertyKey,
): unknown | typeof MISSING_OWN_VALUE {
  if (!value || typeof value !== "object") {
    return MISSING_OWN_VALUE
  }
  const descriptor = Object.getOwnPropertyDescriptor(value, key)
  if (!descriptor || !("value" in descriptor)) {
    return MISSING_OWN_VALUE
  }
  return descriptor.value
}

function ownDataRecord(value: unknown, key: PropertyKey): Record<string, unknown> | null {
  const candidate = ownDataValue(value, key)
  return candidate && typeof candidate === "object" && !Array.isArray(candidate)
    ? (candidate as Record<string, unknown>)
    : null
}

function compilePattern(rawPattern: string, index: number): CompiledPattern {
  let source = rawPattern
  const flags = new Set(["g"])
  while (true) {
    const match = source.match(/^\(\?([ims]+)\)/)
    if (!match) {
      break
    }
    for (const flag of match[1] ?? "") {
      flags.add(flag)
    }
    source = source.slice(match[0].length)
  }
  const normalizedFlags = ["g", "i", "m", "s"].filter((flag) => flags.has(flag)).join("")
  try {
    // Compile once here to reject malformed configured patterns without exposing them.
    new RegExp(source, normalizedFlags)
  } catch {
    throw new SecretRedactionError("invalid_pattern", `index=${index}`)
  }
  return { source, flags: normalizedFlags }
}

function emptyStats(): SecretRedactionStats {
  return { matches: 0, redactedFields: 0, scannedChars: 0, scannedNodes: 0 }
}

export interface SecretRedactor {
  redactText(text: string): { text: string; stats: SecretRedactionStats }
  redactMutableValue(value: unknown): SecretRedactionStats
  redactProviderMessages(messages: unknown): SecretRedactionStats
  redactProviderSystem(system: unknown): SecretRedactionStats
}

export function createSecretRedactor(options: {
  patterns: string[]
  redactionToken: string
  limits: SecretRedactionLimits
  providerLimits?: ProviderSecretRedactionLimits
}): SecretRedactor {
  const patterns = options.patterns.map(compilePattern)
  const limits = {
    maxDepth: normalizedLimit(options.limits.maxDepth, 12),
    maxNodes: normalizedLimit(options.limits.maxNodes, 20_000),
    maxChars: normalizedLimit(options.limits.maxChars, 2 * 1024 * 1024),
  }
  const providerMaxNodes = normalizedLimit(options.providerLimits?.maxNodes ?? 0, 1_000_000)
  const providerMaxChars = normalizedLimit(
    options.providerLimits?.maxChars ?? 0,
    128 * 1024 * 1024,
  )
  const providerLimits = {
    maxMessages: Math.min(
      normalizedLimit(options.providerLimits?.maxMessages ?? 0, 20_000),
      providerMaxNodes,
    ),
    maxNodes: providerMaxNodes,
    maxChars: providerMaxChars,
    maxMessageChars: Math.min(
      normalizedLimit(options.providerLimits?.maxMessageChars ?? 0, 16 * 1024 * 1024),
      providerMaxChars,
    ),
  }

  function createBudget(maxNodes: number, maxChars: number): ResourceBudget {
    return { nodes: 0, chars: 0, maxNodes, maxChars }
  }

  function chargeNode(state: TraversalState, localBudget?: ResourceBudget): void {
    state.budget.nodes += 1
    if (state.budget.nodes > state.budget.maxNodes) {
      throw new SecretRedactionError("node_limit")
    }
    if (localBudget) {
      localBudget.nodes += 1
      if (localBudget.nodes > localBudget.maxNodes) {
        throw new SecretRedactionError("node_limit")
      }
    }
    state.stats.scannedNodes += 1
  }

  function chargeChars(
    text: string,
    budget: ResourceBudget,
    localBudget?: ResourceBudget,
  ): void {
    budget.chars += text.length
    if (budget.chars > budget.maxChars) {
      throw new SecretRedactionError("text_limit")
    }
    if (localBudget) {
      localBudget.chars += text.length
      if (localBudget.chars > localBudget.maxChars) {
        throw new SecretRedactionError("text_limit")
      }
    }
  }

  function applyPatterns(
    text: string,
    stats: SecretRedactionStats,
    budget: ResourceBudget,
    localBudget?: ResourceBudget,
  ): PatternApplication {
    chargeChars(text, budget, localBudget)
    stats.scannedChars += text.length
    let next = text
    let firstPatternIndex: number | null = null
    for (const [patternIndex, pattern] of patterns.entries()) {
      const regex = new RegExp(pattern.source, pattern.flags)
      next = next.replace(regex, () => {
        firstPatternIndex ??= patternIndex
        stats.matches += 1
        return options.redactionToken
      })
    }
    return { text: next, firstPatternIndex }
  }

  function locationCode(
    key: string | number | null,
    parentKey: string | number | null,
    grandparentKey: string | number | null,
  ): SecretRedactionLocationCode {
    if (parentKey === "openai" && grandparentKey === "metadata") {
      return key === "itemId"
        ? "provider_metadata_openai_item_id"
        : "provider_metadata_openai_other"
    }
    if (typeof key === "string" && IMMUTABLE_PROTOCOL_KEYS.has(key)) {
      return "immutable_protocol_field"
    }
    return "unknown_field"
  }

  function immutableMatchError(options: {
    matchTarget: SecretRedactionMatchTarget
    patternIndex: number | null
    key: string | number | null
    parentKey: string | number | null
    grandparentKey: string | number | null
  }): SecretRedactionError {
    if (options.patternIndex === null) {
      return new SecretRedactionError("unexpected_failure")
    }
    return new SecretRedactionError("immutable_match", "", {
      matchTarget: options.matchTarget,
      patternIndex: options.patternIndex,
      locationCode: locationCode(options.key, options.parentKey, options.grandparentKey),
    })
  }

  function isTrustedOpenAIReasoningCiphertext(options: {
    messageRoot: unknown
    parent: Record<string, unknown> | unknown[] | null
    key: string | number | null
    path: PropertyPath
    value: string
  }): boolean {
    const { messageRoot, parent, key, path, value } = options
    if (
      key !== "reasoningEncryptedContent" ||
      path.length !== 5 ||
      path[0] !== "parts" ||
      !Number.isInteger(path[1]) ||
      path[2] !== "metadata" ||
      path[3] !== "openai" ||
      path[4] !== "reasoningEncryptedContent" ||
      value.length === 0
    ) {
      return false
    }

    const info = ownDataRecord(messageRoot, "info")
    const parts = ownDataValue(messageRoot, "parts")
    const partIndex = path[1] as number
    if (
      !info ||
      ownDataValue(info, "role") !== "assistant" ||
      ownDataValue(info, "providerID") !== "openai" ||
      !Array.isArray(parts) ||
      partIndex < 0 ||
      partIndex >= parts.length
    ) {
      return false
    }

    const part = ownDataValue(parts, partIndex)
    if (!part || typeof part !== "object" || ownDataValue(part, "type") !== "reasoning") {
      return false
    }
    const metadata = ownDataRecord(part, "metadata")
    const openai = ownDataRecord(metadata, "openai")
    const itemId = ownDataValue(openai, "itemId")
    return (
      Boolean(openai) &&
      parent === openai &&
      typeof itemId === "string" &&
      /^rs_.+$/.test(itemId) &&
      ownDataValue(openai, "reasoningEncryptedContent") === value
    )
  }

  function toolStateMetadataProjection(options: {
    messageRoot: unknown
    parent: Record<string, unknown> | unknown[] | null
    path: PropertyPath
    value: unknown
  }): ToolStateMetadataProjection {
    const { messageRoot, parent, path, value } = options
    if (
      path.length !== 4 ||
      path[0] !== "parts" ||
      !Number.isInteger(path[1]) ||
      path[2] !== "state" ||
      path[3] !== "metadata"
    ) {
      return null
    }

    const info = ownDataRecord(messageRoot, "info")
    const parts = ownDataValue(messageRoot, "parts")
    const partIndex = path[1] as number
    if (
      !info ||
      ownDataValue(info, "role") !== "assistant" ||
      !Array.isArray(parts) ||
      partIndex < 0 ||
      partIndex >= parts.length
    ) {
      return null
    }
    const part = ownDataValue(parts, partIndex)
    if (
      !part ||
      typeof part !== "object" ||
      Array.isArray(part) ||
      ownDataValue(part, "type") !== "tool"
    ) {
      return null
    }
    const state = ownDataRecord(part, "state")
    const metadata = ownDataRecord(state, "metadata")
    if (!state || parent !== state || !metadata || value !== metadata) {
      return null
    }

    const status = ownDataValue(state, "status")
    if (status === "completed" || status === "pending" || status === "running") {
      return { kind: "skip" }
    }
    if (status !== "error") {
      throw new SecretRedactionError("malformed_provider_metadata")
    }

    const interrupted = ownDataValue(metadata, "interrupted")
    if (interrupted === MISSING_OWN_VALUE) {
      if ("interrupted" in metadata) {
        throw new SecretRedactionError("malformed_provider_metadata")
      }
      return { kind: "skip" }
    }
    if (interrupted === false) {
      return { kind: "skip" }
    }
    if (interrupted !== true) {
      throw new SecretRedactionError("malformed_provider_metadata")
    }

    const output = ownDataValue(metadata, "output")
    if (output === MISSING_OWN_VALUE && !("output" in metadata)) {
      return { kind: "skip" }
    }
    if (typeof output !== "string") {
      throw new SecretRedactionError("malformed_provider_metadata")
    }
    return { kind: "output", value: output }
  }

  function assignValue(
    parent: Record<string, unknown> | unknown[] | null,
    key: string | number | null,
    value: string,
  ): void {
    if (parent === null || key === null) {
      throw new SecretRedactionError("mutation_failed")
    }
    try {
      if (Array.isArray(parent) && typeof key === "number") {
        parent[key] = value
      } else if (!Array.isArray(parent) && typeof key === "string") {
        parent[key] = value
      } else {
        throw new SecretRedactionError("mutation_failed")
      }
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("mutation_failed")
    }
  }

  function childMode(parentMode: VisitMode, key: string): VisitMode {
    if (IMMUTABLE_PROTOCOL_KEYS.has(key)) {
      return "scan"
    }
    if (MUTABLE_CONTENT_KEYS.has(key)) {
      return "redact"
    }
    return parentMode
  }

  function createTraversalState(
    traversalLimits: SecretRedactionLimits,
    revisitAliases: boolean,
  ): TraversalState {
    return {
      stats: emptyStats(),
      budget: createBudget(traversalLimits.maxNodes, traversalLimits.maxChars),
      maxDepth: traversalLimits.maxDepth,
      active: new WeakSet<object>(),
      visited: new WeakSet<object>(),
      revisitAliases,
    }
  }

  function visit(
    value: unknown,
    parent: Record<string, unknown> | unknown[] | null,
    key: string | number | null,
    mode: VisitMode,
    depth: number,
    parentKey: string | number | null,
    grandparentKey: string | number | null,
    path: PropertyPath,
    state: TraversalState,
    localBudget?: ResourceBudget,
    messageRoot?: unknown,
  ): void {
    chargeNode(state, localBudget)
    if (depth > state.maxDepth) {
      throw new SecretRedactionError("depth_limit")
    }

    if (typeof value === "string") {
      if (
        messageRoot !== undefined &&
        isTrustedOpenAIReasoningCiphertext({ messageRoot, parent, key, path, value })
      ) {
        chargeChars(value, state.budget, localBudget)
        return
      }
      const applied = applyPatterns(value, state.stats, state.budget, localBudget)
      if (applied.text === value) {
        return
      }
      if (mode === "scan") {
        throw immutableMatchError({
          matchTarget: "value",
          patternIndex: applied.firstPatternIndex,
          key,
          parentKey,
          grandparentKey,
        })
      }
      assignValue(parent, key, applied.text)
      state.stats.redactedFields += 1
      return
    }
    if (messageRoot !== undefined) {
      const projection = toolStateMetadataProjection({ messageRoot, parent, path, value })
      if (projection) {
        if (projection.kind === "output") {
          const outputKey = "output"
          const keyProbe = applyPatterns(
            outputKey,
            state.stats,
            state.budget,
            localBudget,
          )
          if (keyProbe.text !== outputKey) {
            throw immutableMatchError({
              matchTarget: "key",
              patternIndex: keyProbe.firstPatternIndex,
              key: outputKey,
              parentKey: key,
              grandparentKey: parentKey,
            })
          }
          visit(
            projection.value,
            value as Record<string, unknown>,
            outputKey,
            "redact",
            depth + 1,
            key,
            parentKey,
            [...path, outputKey],
            state,
            localBudget,
            messageRoot,
          )
        }
        return
      }
    }
    if (!value || typeof value !== "object") {
      return
    }
    if (state.active.has(value)) {
      throw new SecretRedactionError("cycle_detected")
    }
    if (!state.revisitAliases && state.visited.has(value)) {
      return
    }
    state.active.add(value)

    if (Array.isArray(value)) {
      for (let index = 0; index < value.length; index += 1) {
        visit(
          value[index],
          value,
          index,
          mode,
          depth + 1,
          key,
          parentKey,
          [...path, index],
          state,
          localBudget,
          messageRoot,
        )
      }
    } else {
      const record = value as Record<string, unknown>
      for (const childKey of Object.keys(record)) {
        const keyProbe = applyPatterns(
          childKey,
          state.stats,
          state.budget,
          localBudget,
        )
        if (keyProbe.text !== childKey) {
          throw immutableMatchError({
            matchTarget: "key",
            patternIndex: keyProbe.firstPatternIndex,
            key: childKey,
            parentKey: key,
            grandparentKey: parentKey,
          })
        }
        visit(
          record[childKey],
          record,
          childKey,
          childMode(mode, childKey),
          depth + 1,
          key,
          parentKey,
          [...path, childKey],
          state,
          localBudget,
          messageRoot,
        )
      }
    }
    state.active.delete(value)
    state.visited.add(value)
  }

  function traverse(root: unknown, initialMode: VisitMode): SecretRedactionStats {
    const state = createTraversalState(limits, false)
    try {
      visit(root, null, null, initialMode, 0, null, null, [], state)
      return state.stats
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("unexpected_failure")
    }
  }

  function traverseProviderMessages(messages: unknown): SecretRedactionStats {
    if (!Array.isArray(messages)) {
      return traverse(messages, "scan")
    }
    if (messages.length > providerLimits.maxMessages) {
      throw new SecretRedactionError("node_limit")
    }
    const state = createTraversalState(
      {
        maxDepth: limits.maxDepth,
        maxNodes: providerLimits.maxNodes,
        maxChars: providerLimits.maxChars,
      },
      true,
    )
    try {
      chargeNode(state)
      state.active.add(messages)
      for (let index = 0; index < messages.length; index += 1) {
        const message = messages[index]
        const localBudget = createBudget(limits.maxNodes, providerLimits.maxMessageChars)
        visit(
          message,
          messages,
          index,
          "scan",
          1,
          null,
          null,
          [],
          state,
          localBudget,
          message,
        )
      }
      state.active.delete(messages)
      state.visited.add(messages)
      return state.stats
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("unexpected_failure")
    }
  }

  return {
    redactText(text: string): { text: string; stats: SecretRedactionStats } {
      const stats = emptyStats()
      const budget = createBudget(limits.maxNodes, limits.maxChars)
      const redacted = applyPatterns(text, stats, budget)
      if (redacted.text !== text) {
        stats.redactedFields = 1
      }
      return { text: redacted.text, stats }
    },
    redactMutableValue(value: unknown): SecretRedactionStats {
      return traverse(value, "redact")
    },
    redactProviderMessages(messages: unknown): SecretRedactionStats {
      return traverseProviderMessages(messages)
    },
    redactProviderSystem(system: unknown): SecretRedactionStats {
      return traverse(system, "redact")
    },
  }
}
