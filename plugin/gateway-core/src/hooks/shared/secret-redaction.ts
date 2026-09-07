import { createHash } from "node:crypto"
import { isProxy } from "node:util/types"
import { Worker } from "node:worker_threads"

import { DEFAULT_GATEWAY_CONFIG } from "../../config/schema.js"
import { parseCanonicalProviderAttachmentDataUrl } from "./provider-attachment-data-url.js"
import {
  SECRET_REDACTION_WORKER_PROTOCOL_VERSION,
  type PatternWorkerApplyResult,
  type PatternWorkerAttachmentResult,
  type PatternWorkerMatchResult,
  type PatternWorkerOperation,
  type PatternWorkerPattern,
  type PatternWorkerResponse,
  type PatternWorkerResult,
  type PatternWorkerSpan,
} from "./secret-redaction-worker-protocol.js"

export type SecretRedactionErrorCode =
  | "invalid_pattern"
  | "invalid_redaction_token"
  | "immutable_match"
  | "cycle_detected"
  | "depth_limit"
  | "node_limit"
  | "text_limit"
  | "malformed_provider_object"
  | "malformed_provider_metadata"
  | "mutation_failed"
  | "regex_timeout"
  | "regex_capacity"
  | "regex_batch_limit"
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
  omittedOpaqueAttachmentMatches: number
}

interface CompiledPattern {
  index: number
  source: string
  flags: string
}

interface PatternApplication {
  text: string
  firstPatternIndex: number | null
  deferredOperationIndex: number | null
}

interface PatternApplicationOptions {
  charge?: boolean
  batch?: PatternBatch | null
  inputOperationIndex?: number | null
  onDeferred?: (
    result: PatternWorkerApplyResult,
    materialized: PatternApplyMaterialized,
  ) => void
}

interface PatternWorkerLike {
  postMessage(message: unknown): void
  once(event: "message", listener: (message: unknown) => void): this
  once(event: "error", listener: (error: unknown) => void): this
  once(event: "exit", listener: (code: number) => void): this
  terminate(): Promise<number>
}

export type SecretRedactionWorkerFactory = (url: URL) => PatternWorkerLike

interface PatternBatchObjectSnapshot {
  value: object
  prototype: object | null
  keys: PropertyKey[]
  descriptors: Array<{ key: PropertyKey; descriptor: PropertyDescriptor }>
}

interface PatternBatchAssignment {
  parent: Record<string, unknown> | unknown[]
  key: string | number
  originalValue: unknown
  value: string
}

interface PatternBatch {
  operations: PatternWorkerOperation[]
  actions: Array<
    (
      results: PatternWorkerResult[],
      context: PatternBatchExecutionContext,
    ) => void
  >
  objectSnapshots: PatternBatchObjectSnapshot[]
  objectSnapshotSet: WeakSet<object>
  lastApplyOperations: WeakMap<object, Map<PropertyKey, number>>
  assignments: Map<object, Map<PropertyKey, PatternBatchAssignment>>
  reservedInputChars: number
  maxInputChars: number
}

interface PatternBatchExecutionContext {
  applyOutputs: Map<number, string>
  matchSpans: number
  outputCharsAllocated: number
}

interface PatternScanResult {
  blockingPatternIndex: number | null
  deferredOperationIndex: number | null
}

interface PatternApplyMaterialized {
  text: string
  inputText: string
  inputLength: number
  firstPatternIndex: number | null
  residualPatternIndex: number | null
  matchCount: number
  positiveExpansion: number
}

type VisitMode = "redact" | "root-scan" | "immutable-scan"
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
  strictProviderObjects: boolean
  patternBatch: PatternBatch | null
}

type ToolStateMetadataProjection =
  | { kind: "skip" }
  | { kind: "output"; value: string }
  | null

const MISSING_OWN_VALUE = Symbol("missing-own-value")
const OPAQUE_ATTACHMENT_FALSE_POSITIVE_PATTERN_SOURCE =
  "AIza[0-9A-Za-z\\-_]{20,}"
const OPAQUE_ATTACHMENT_FALSE_POSITIVE_PATTERN_FLAGS = "g"
const OPAQUE_ATTACHMENT_PATTERN_PREFIX = "AIza"
const OPAQUE_ATTACHMENT_PATTERN_MIN_SUFFIX_LENGTH = 20
const MAX_REDACTION_TOKEN_BYTES = 256
const MAX_PATTERN_COUNT = 64
const MAX_PATTERN_SOURCE_BYTES = 16 * 1024
const MAX_PATTERN_TOTAL_BYTES = 128 * 1024
const MAX_ISOLATED_BATCH_OPERATIONS = 8192
const MAX_ISOLATED_BATCH_CHARS = 8 * 1024 * 1024
const MAX_ISOLATED_OUTPUT_CHARS = 64 * 1024 * 1024
const MAX_ISOLATED_SNAPSHOTS = 100_000
const MAX_ISOLATED_MATCH_SPANS = 100_000
const MAX_ACTIVE_PATTERN_WORKERS = 2
const DEFAULT_PATTERN_WORKER_TIMEOUT_MS = 1000
const STANDARD_OBJECT_PROTOTYPE_KEYS = new Set<PropertyKey>([
  "constructor",
  "__defineGetter__",
  "__defineSetter__",
  "hasOwnProperty",
  "__lookupGetter__",
  "__lookupSetter__",
  "isPrototypeOf",
  "propertyIsEnumerable",
  "toString",
  "valueOf",
  "__proto__",
  "toLocaleString",
])

let activePatternWorkers = 0
let patternWorkerRequestCounter = 0

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length
}

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
  if (!value || typeof value !== "object" || isProxy(value)) {
    return MISSING_OWN_VALUE
  }
  const descriptor = Object.getOwnPropertyDescriptor(value, key)
  if (!descriptor || !("value" in descriptor)) {
    return MISSING_OWN_VALUE
  }
  return descriptor.value
}

function ownDataRecord(
  value: unknown,
  key: PropertyKey,
): Record<string, unknown> | null {
  const candidate = ownDataValue(value, key)
  return candidate && typeof candidate === "object" && !Array.isArray(candidate)
    ? (candidate as Record<string, unknown>)
    : null
}

function compilePattern(rawPattern: string, index: number): CompiledPattern {
  if (
    typeof rawPattern !== "string" ||
    rawPattern.length > MAX_PATTERN_SOURCE_BYTES ||
    utf8ByteLength(rawPattern) > MAX_PATTERN_SOURCE_BYTES
  ) {
    throw new SecretRedactionError("invalid_pattern", `index=${index}`)
  }
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
  if (
    source.length > MAX_PATTERN_SOURCE_BYTES ||
    utf8ByteLength(source) > MAX_PATTERN_SOURCE_BYTES
  ) {
    throw new SecretRedactionError("invalid_pattern", `index=${index}`)
  }
  const normalizedFlags = ["g", "i", "m", "s"]
    .filter((flag) => flags.has(flag))
    .join("")
  try {
    // Compile once here to reject malformed configured patterns without exposing them.
    new RegExp(source, normalizedFlags)
  } catch {
    throw new SecretRedactionError("invalid_pattern", `index=${index}`)
  }
  return { index, source, flags: normalizedFlags }
}

const DEFAULT_COMPILED_PATTERN_PROFILE =
  DEFAULT_GATEWAY_CONFIG.secretLeakGuard.patterns.map(compilePattern)

function matchesDefaultPatternProfile(patterns: CompiledPattern[]): boolean {
  return (
    patterns.length === DEFAULT_COMPILED_PATTERN_PROFILE.length &&
    patterns.every(
      (pattern, index) =>
        pattern.index === index &&
        pattern.source === DEFAULT_COMPILED_PATTERN_PROFILE[index]?.source &&
        pattern.flags === DEFAULT_COMPILED_PATTERN_PROFILE[index]?.flags,
    )
  )
}

function isOpaqueAttachmentPatternCharacter(charCode: number): boolean {
  return (
    (charCode >= 0x30 && charCode <= 0x39) ||
    (charCode >= 0x41 && charCode <= 0x5a) ||
    (charCode >= 0x61 && charCode <= 0x7a) ||
    charCode === 0x2d ||
    charCode === 0x5f
  )
}

function* opaqueAttachmentPatternMatches(
  value: string,
): Generator<{ start: number; end: number }> {
  let searchFrom = 0
  while (searchFrom < value.length) {
    const start = value.indexOf(OPAQUE_ATTACHMENT_PATTERN_PREFIX, searchFrom)
    if (start < 0) return
    const suffixStart = start + OPAQUE_ATTACHMENT_PATTERN_PREFIX.length
    let end = suffixStart
    while (
      end < value.length &&
      isOpaqueAttachmentPatternCharacter(value.charCodeAt(end))
    ) {
      end += 1
    }
    if (end - suffixStart >= OPAQUE_ATTACHMENT_PATTERN_MIN_SUFFIX_LENGTH) {
      yield { start, end }
      searchFrom = end
    } else {
      searchFrom = start + 1
    }
  }
}

function isLinearOpaqueAttachmentPattern(pattern: CompiledPattern): boolean {
  return (
    pattern.source === OPAQUE_ATTACHMENT_FALSE_POSITIVE_PATTERN_SOURCE &&
    pattern.flags === OPAQUE_ATTACHMENT_FALSE_POSITIVE_PATTERN_FLAGS
  )
}

function patternMatches(value: string, pattern: CompiledPattern): boolean {
  if (isLinearOpaqueAttachmentPattern(pattern)) {
    for (const _match of opaqueAttachmentPatternMatches(value)) return true
    return false
  }
  return new RegExp(pattern.source, pattern.flags).test(value)
}

function firstPatternMatch(
  value: string,
  patterns: CompiledPattern[],
): number | null {
  for (const pattern of patterns) {
    if (patternMatches(value, pattern)) return pattern.index
  }
  return null
}

function validateRedactionToken(
  redactionToken: unknown,
  patterns: CompiledPattern[],
  checkPatternMatch = true,
): asserts redactionToken is string {
  if (
    typeof redactionToken !== "string" ||
    redactionToken.length > MAX_REDACTION_TOKEN_BYTES ||
    redactionToken.trim().length === 0 ||
    Buffer.byteLength(redactionToken, "utf8") > MAX_REDACTION_TOKEN_BYTES ||
    (checkPatternMatch && firstPatternMatch(redactionToken, patterns) !== null)
  ) {
    throw new SecretRedactionError("invalid_redaction_token")
  }
}

function emptyStats(): SecretRedactionStats {
  return {
    matches: 0,
    redactedFields: 0,
    scannedChars: 0,
    scannedNodes: 0,
    omittedOpaqueAttachmentMatches: 0,
  }
}

function createPatternBatch(): PatternBatch {
  return {
    operations: [],
    actions: [],
    objectSnapshots: [],
    objectSnapshotSet: new WeakSet<object>(),
    lastApplyOperations: new WeakMap<object, Map<PropertyKey, number>>(),
    assignments: new Map<object, Map<PropertyKey, PatternBatchAssignment>>(),
    reservedInputChars: 0,
    maxInputChars: MAX_ISOLATED_BATCH_CHARS,
  }
}

function queuePatternOperation(
  batch: PatternBatch,
  operation: PatternWorkerOperation,
): number {
  if (
    batch.operations.length >= MAX_ISOLATED_BATCH_OPERATIONS ||
    batch.reservedInputChars + operation.text.length > batch.maxInputChars
  ) {
    throw new SecretRedactionError("regex_batch_limit")
  }
  const operationIndex = batch.operations.length
  if (operation.operationIndex !== operationIndex) {
    throw new SecretRedactionError("unexpected_failure")
  }
  batch.operations.push(operation)
  batch.reservedInputChars += operation.text.length
  return operationIndex
}

function queuePatternAction(
  batch: PatternBatch,
  operationIndex: number,
  action: (
    result: PatternWorkerResult,
    context: PatternBatchExecutionContext,
  ) => void,
): void {
  batch.actions.push((results, context) => {
    const result = results[operationIndex]
    if (!result || result.operationIndex !== operationIndex) {
      throw new SecretRedactionError("unexpected_failure")
    }
    action(result, context)
  })
}

function defaultPatternWorkerFactory(url: URL): PatternWorkerLike {
  return new Worker(url, {
    type: "module",
    execArgv: [],
  } as ConstructorParameters<typeof Worker>[1])
}

function workerResultError(errorCode: unknown): SecretRedactionError {
  return new SecretRedactionError(
    errorCode === "invalid_pattern" ? "invalid_pattern" : "unexpected_failure",
  )
}

function decodePatternWorkerResponse(
  response: unknown,
  requestId: string,
  operationCount: number,
): PatternWorkerResult[] {
  if (!response || typeof response !== "object" || Array.isArray(response)) {
    throw new SecretRedactionError("unexpected_failure")
  }
  const candidate = response as Record<string, unknown>
  if (
    candidate.version !== SECRET_REDACTION_WORKER_PROTOCOL_VERSION ||
    candidate.requestId !== requestId ||
    typeof candidate.ok !== "boolean"
  ) {
    throw new SecretRedactionError("unexpected_failure")
  }
  if (candidate.ok !== true) {
    throw workerResultError(candidate.errorCode)
  }
  if (
    !Array.isArray(candidate.results) ||
    candidate.results.length !== operationCount
  ) {
    throw new SecretRedactionError("unexpected_failure")
  }
  const results = candidate.results as PatternWorkerResult[]
  for (let index = 0; index < results.length; index += 1) {
    const result = results[index]
    if (
      !result ||
      typeof result !== "object" ||
      Array.isArray(result) ||
      result.operationIndex !== index ||
      (result.kind !== "match" &&
        result.kind !== "apply" &&
        result.kind !== "attachment")
    ) {
      throw new SecretRedactionError("unexpected_failure")
    }
  }
  return results
}

async function runPatternWorker(options: {
  batch: PatternBatch
  patterns: CompiledPattern[]
  redactionToken: string
  workerFactory: SecretRedactionWorkerFactory
  timeoutMs: number
}): Promise<PatternWorkerResult[]> {
  if (activePatternWorkers >= MAX_ACTIVE_PATTERN_WORKERS) {
    throw new SecretRedactionError("regex_capacity")
  }
  activePatternWorkers += 1
  const requestId = `redaction-${(patternWorkerRequestCounter += 1)}`
  const request = {
    version: SECRET_REDACTION_WORKER_PROTOCOL_VERSION,
    requestId,
    redactionToken: options.redactionToken,
    patterns: options.patterns.map(
      ({ index, source, flags }): PatternWorkerPattern => ({
        index,
        source,
        flags,
      }),
    ),
    operations: options.batch.operations,
  }
  let worker: PatternWorkerLike
  try {
    worker = options.workerFactory(
      new URL("./secret-redaction-worker.js", import.meta.url),
    )
  } catch {
    activePatternWorkers -= 1
    throw new SecretRedactionError("unexpected_failure")
  }

  try {
    return await new Promise<PatternWorkerResult[]>((resolve, reject) => {
      let settled = false
      const timeoutMs = Math.max(1, Math.floor(options.timeoutMs))
      const timer = setTimeout(() => {
        void finish(new SecretRedactionError("regex_timeout"))
      }, timeoutMs)

      const finish = async (
        error: SecretRedactionError | null,
        result: PatternWorkerResult[] | null = null,
      ): Promise<void> => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        await worker.terminate().catch(() => undefined)
        if (error) reject(error)
        else if (result) resolve(result)
        else reject(new SecretRedactionError("unexpected_failure"))
      }

      try {
        worker.once("message", (response) => {
          try {
            void finish(
              null,
              decodePatternWorkerResponse(
                response,
                requestId,
                options.batch.operations.length,
              ),
            )
          } catch (error) {
            void finish(
              error instanceof SecretRedactionError
                ? error
                : new SecretRedactionError("unexpected_failure"),
            )
          }
        })
        worker.once("error", () => {
          void finish(new SecretRedactionError("unexpected_failure"))
        })
        worker.once("exit", (code) => {
          if (code !== 0) {
            void finish(new SecretRedactionError("unexpected_failure"))
          } else if (!settled) {
            void finish(new SecretRedactionError("unexpected_failure"))
          }
        })
        worker.postMessage(request)
      } catch {
        void finish(new SecretRedactionError("unexpected_failure"))
      }
    })
  } finally {
    activePatternWorkers -= 1
  }
}

function descriptorEqual(
  left: PropertyDescriptor,
  right: PropertyDescriptor,
): boolean {
  if (
    left.enumerable !== right.enumerable ||
    left.configurable !== right.configurable ||
    "value" in left !== "value" in right
  ) {
    return false
  }
  if ("value" in left && "value" in right) {
    return (
      left.writable === right.writable && Object.is(left.value, right.value)
    )
  }
  return left.get === right.get && left.set === right.set
}

function capturePatternBatchSnapshot(batch: PatternBatch, value: object): void {
  if (batch.objectSnapshotSet.has(value)) return
  if (
    batch.objectSnapshots.length >= MAX_ISOLATED_SNAPSHOTS ||
    isProxy(value)
  ) {
    throw new SecretRedactionError(
      batch.objectSnapshots.length >= MAX_ISOLATED_SNAPSHOTS
        ? "regex_batch_limit"
        : "malformed_provider_object",
    )
  }
  try {
    const keys = Reflect.ownKeys(value)
    const descriptors = keys.map((key) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, key)
      if (!descriptor) throw new SecretRedactionError("mutation_failed")
      return { key, descriptor }
    })
    const prototype = Object.getPrototypeOf(value)
    batch.objectSnapshotSet.add(value)
    batch.objectSnapshots.push({ value, prototype, keys, descriptors })
  } catch (error) {
    if (error instanceof SecretRedactionError) throw error
    throw new SecretRedactionError("mutation_failed")
  }
}

function isolatedOwnDataChildren(
  value: object,
): Array<[string | number, unknown]> {
  if (isProxy(value)) {
    throw new SecretRedactionError("malformed_provider_object")
  }
  try {
    if (Array.isArray(value)) {
      const array = value as unknown[]
      const children: Array<[number, unknown]> = []
      for (let index = 0; index < array.length; index += 1) {
        const descriptor = Object.getOwnPropertyDescriptor(array, String(index))
        if (descriptor && !("value" in descriptor)) {
          throw new SecretRedactionError("malformed_provider_object")
        }
        children.push([
          index,
          descriptor && "value" in descriptor ? descriptor.value : undefined,
        ])
      }
      return children
    }
    const children: Array<[string, unknown]> = []
    for (const childKey of Object.keys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, childKey)
      if (!descriptor || !("value" in descriptor)) {
        throw new SecretRedactionError("malformed_provider_object")
      }
      children.push([childKey, descriptor.value])
    }
    return children
  } catch (error) {
    if (error instanceof SecretRedactionError) throw error
    throw new SecretRedactionError("malformed_provider_object")
  }
}

function validatePatternBatchSnapshots(batch: PatternBatch): void {
  for (const snapshot of batch.objectSnapshots) {
    try {
      if (
        Object.getPrototypeOf(snapshot.value) !== snapshot.prototype ||
        !Reflect.ownKeys(snapshot.value).every(
          (key, index) => key === snapshot.keys[index],
        ) ||
        Reflect.ownKeys(snapshot.value).length !== snapshot.keys.length
      ) {
        throw new SecretRedactionError("mutation_failed")
      }
      for (const { key, descriptor } of snapshot.descriptors) {
        const current = Object.getOwnPropertyDescriptor(snapshot.value, key)
        if (!current || !descriptorEqual(current, descriptor)) {
          throw new SecretRedactionError("mutation_failed")
        }
      }
    } catch (error) {
      if (error instanceof SecretRedactionError) throw error
      throw new SecretRedactionError("mutation_failed")
    }
  }
}

function validPatternIndex(
  index: number | null,
  patterns: CompiledPattern[],
): boolean {
  return (
    index === null ||
    (Number.isInteger(index) && index >= 0 && index < patterns.length)
  )
}

function applyPatternSpans(
  value: string,
  matches: PatternWorkerSpan[],
  replacement: string,
  budget: PatternBatchExecutionContext | null = null,
): string {
  if (matches.length > MAX_ISOLATED_MATCH_SPANS) {
    throw new SecretRedactionError("unexpected_failure")
  }
  let replacementLength = value.length
  let previousEnd = 0
  for (const match of matches) {
    if (
      !Number.isSafeInteger(match.start) ||
      !Number.isSafeInteger(match.end) ||
      match.start < previousEnd ||
      match.end < match.start ||
      match.end > value.length
    ) {
      throw new SecretRedactionError("unexpected_failure")
    }
    replacementLength += replacement.length - (match.end - match.start)
    if (replacementLength > MAX_ISOLATED_OUTPUT_CHARS) {
      throw new SecretRedactionError("unexpected_failure")
    }
    previousEnd = match.end
  }
  if (matches.length === 0) return value
  if (budget) {
    budget.outputCharsAllocated += replacementLength
    if (budget.outputCharsAllocated > MAX_ISOLATED_OUTPUT_CHARS) {
      throw new SecretRedactionError("unexpected_failure")
    }
  }
  const parts: string[] = []
  let cursor = 0
  for (const match of matches) {
    parts.push(value.slice(cursor, match.start), replacement)
    cursor = match.end
  }
  parts.push(value.slice(cursor))
  return parts.join("")
}

function operationInputText(
  operation: PatternWorkerOperation,
  context: PatternBatchExecutionContext,
): string {
  if (operation.kind === "match") return operation.text
  if (operation.inputOperationIndex === null) return operation.text
  const input = context.applyOutputs.get(operation.inputOperationIndex)
  if (input === undefined) throw new SecretRedactionError("unexpected_failure")
  return input
}

function materializeApplyResult(options: {
  result: PatternWorkerApplyResult
  batch: PatternBatch
  patterns: CompiledPattern[]
  redactionToken: string
  context: PatternBatchExecutionContext
}): PatternApplyMaterialized {
  const { result, batch, patterns, redactionToken, context } = options
  const operation = batch.operations[result.operationIndex]
  if (!operation || operation.kind !== "apply") {
    throw new SecretRedactionError("unexpected_failure")
  }
  if (
    operation.inputOperationIndex !== null &&
    (operation.inputOperationIndex >= result.operationIndex ||
      batch.operations[operation.inputOperationIndex]?.kind !== "apply")
  ) {
    throw new SecretRedactionError("unexpected_failure")
  }
  const inputText = operationInputText(operation, context)
  if (
    !Number.isSafeInteger(result.inputLength) ||
    result.inputLength !== inputText.length ||
    !Array.isArray(result.steps) ||
    result.steps.length !== patterns.length ||
    !Number.isSafeInteger(result.matchCount) ||
    result.matchCount < 0 ||
    !Number.isSafeInteger(result.positiveExpansion) ||
    result.positiveExpansion < 0 ||
    !validPatternIndex(result.firstPatternIndex, patterns) ||
    !validPatternIndex(result.residualPatternIndex, patterns) ||
    (result.firstPatternIndex === null &&
      result.residualPatternIndex !== null) ||
    !Number.isSafeInteger(result.finalLength) ||
    result.finalLength < 0 ||
    !/^[0-9a-f]{64}$/.test(result.finalSha256)
  ) {
    throw new SecretRedactionError("unexpected_failure")
  }

  let current = inputText
  let firstPatternIndex: number | null = null
  let matchCount = 0
  let positiveExpansion = 0
  for (let index = 0; index < result.steps.length; index += 1) {
    const step = result.steps[index]
    if (
      !step ||
      typeof step !== "object" ||
      step.patternIndex !== patterns[index]?.index ||
      !Array.isArray(step.matches)
    ) {
      throw new SecretRedactionError("unexpected_failure")
    }
    if (step.matches.length > MAX_ISOLATED_MATCH_SPANS) {
      throw new SecretRedactionError("unexpected_failure")
    }
    if (step.matches.length > 0) firstPatternIndex ??= step.patternIndex
    for (const match of step.matches) {
      if (!match || typeof match !== "object") {
        throw new SecretRedactionError("unexpected_failure")
      }
      matchCount += 1
      positiveExpansion += Math.max(
        0,
        redactionToken.length - (match.end - match.start),
      )
    }
    context.matchSpans += step.matches.length
    if (context.matchSpans > MAX_ISOLATED_MATCH_SPANS) {
      throw new SecretRedactionError("unexpected_failure")
    }
    current = applyPatternSpans(current, step.matches, redactionToken, context)
  }
  if (
    firstPatternIndex !== result.firstPatternIndex ||
    matchCount !== result.matchCount ||
    positiveExpansion !== result.positiveExpansion ||
    current.length !== result.finalLength ||
    createHash("sha256").update(current, "utf8").digest("hex") !==
      result.finalSha256
  ) {
    throw new SecretRedactionError("unexpected_failure")
  }
  context.applyOutputs.set(result.operationIndex, current)
  return {
    text: current,
    inputText,
    inputLength: result.inputLength,
    firstPatternIndex: result.firstPatternIndex,
    residualPatternIndex: result.residualPatternIndex,
    matchCount: result.matchCount,
    positiveExpansion: result.positiveExpansion,
  }
}

function materializeMatchResult(
  result: PatternWorkerMatchResult,
  patterns: CompiledPattern[],
): number | null {
  if (!validPatternIndex(result.firstPatternIndex, patterns)) {
    throw new SecretRedactionError("unexpected_failure")
  }
  return result.firstPatternIndex
}

function materializeAttachmentResult(options: {
  result: PatternWorkerAttachmentResult
  batch: PatternBatch
  patterns: CompiledPattern[]
  context: PatternBatchExecutionContext
}): {
  inputText: string
  blockingPatternIndex: number | null
  matchSpanCount: number
  omittedMatchCount: number
} {
  const { result, batch, patterns, context } = options
  const operation = batch.operations[result.operationIndex]
  if (!operation || operation.kind !== "attachment") {
    throw new SecretRedactionError("unexpected_failure")
  }
  const inputText = operationInputText(operation, context)
  if (
    !Number.isSafeInteger(result.inputLength) ||
    result.inputLength !== inputText.length ||
    !validPatternIndex(result.blockingPatternIndex, patterns) ||
    !Number.isSafeInteger(result.matchSpanCount) ||
    result.matchSpanCount < 0 ||
    result.matchSpanCount > MAX_ISOLATED_MATCH_SPANS ||
    !Number.isSafeInteger(result.omittedMatchCount) ||
    result.omittedMatchCount < 0 ||
    result.omittedMatchCount > MAX_ISOLATED_MATCH_SPANS
  ) {
    throw new SecretRedactionError("unexpected_failure")
  }
  context.matchSpans += result.matchSpanCount
  if (context.matchSpans > MAX_ISOLATED_MATCH_SPANS) {
    throw new SecretRedactionError("unexpected_failure")
  }
  return {
    inputText,
    blockingPatternIndex: result.blockingPatternIndex,
    matchSpanCount: result.matchSpanCount,
    omittedMatchCount: result.omittedMatchCount,
  }
}

function schedulePatternAssignment(
  batch: PatternBatch,
  parent: Record<string, unknown> | unknown[] | null,
  key: string | number | null,
  originalValue: string,
  value: string,
): void {
  if (parent === null || key === null) {
    throw new SecretRedactionError("mutation_failed")
  }
  let target = batch.assignments.get(parent)
  if (!target) {
    target = new Map<PropertyKey, PatternBatchAssignment>()
    batch.assignments.set(parent, target)
  }
  const existing = target.get(key)
  if (existing) {
    existing.value = value
  } else {
    target.set(key, { parent, key, originalValue, value })
  }
}

function validatePatternBatchAssignments(batch: PatternBatch): void {
  for (const target of batch.assignments.values()) {
    for (const assignment of target.values()) {
      const descriptor = Object.getOwnPropertyDescriptor(
        assignment.parent,
        assignment.key,
      )
      if (
        !descriptor ||
        !("value" in descriptor) ||
        descriptor.writable === false ||
        !Object.is(descriptor.value, assignment.originalValue)
      ) {
        throw new SecretRedactionError("mutation_failed")
      }
    }
  }
}

function commitPatternBatchAssignments(batch: PatternBatch): void {
  validatePatternBatchAssignments(batch)
  try {
    for (const target of batch.assignments.values()) {
      for (const assignment of target.values()) {
        const descriptor = Object.getOwnPropertyDescriptor(
          assignment.parent,
          assignment.key,
        )
        if (!descriptor || !("value" in descriptor)) {
          throw new SecretRedactionError("mutation_failed")
        }
        if (!Object.is(descriptor.value, assignment.value)) {
          if (Array.isArray(assignment.parent)) {
            assignment.parent[assignment.key as number] = assignment.value
          } else {
            assignment.parent[assignment.key as string] = assignment.value
          }
        }
      }
    }
  } catch (error) {
    if (error instanceof SecretRedactionError) throw error
    throw new SecretRedactionError("mutation_failed")
  }
}

async function executePatternBatch(options: {
  batch: PatternBatch
  patterns: CompiledPattern[]
  redactionToken: string
  workerFactory: SecretRedactionWorkerFactory
  timeoutMs: number
}): Promise<void> {
  const results = await runPatternWorker(options)
  const context: PatternBatchExecutionContext = {
    applyOutputs: new Map(),
    matchSpans: 0,
    outputCharsAllocated: 0,
  }
  validatePatternBatchSnapshots(options.batch)
  for (const action of options.batch.actions) {
    action(results, context)
  }
  validatePatternBatchSnapshots(options.batch)
  commitPatternBatchAssignments(options.batch)
}

export interface SecretRedactor {
  readonly usesIsolatedPatterns: boolean
  redactText(text: string): { text: string; stats: SecretRedactionStats }
  redactMutableValue(value: unknown): SecretRedactionStats
  redactProviderMessages(messages: unknown): SecretRedactionStats
  redactProviderSystem(system: unknown): SecretRedactionStats
  redactTextAsync(
    text: string,
  ): Promise<{ text: string; stats: SecretRedactionStats }>
  redactMutableValueAsync(value: unknown): Promise<SecretRedactionStats>
  redactProviderMessagesAsync(messages: unknown): Promise<SecretRedactionStats>
  redactProviderSystemAsync(system: unknown): Promise<SecretRedactionStats>
}

export function createSecretRedactor(options: {
  patterns: string[]
  redactionToken: string
  limits: SecretRedactionLimits
  providerLimits?: ProviderSecretRedactionLimits
  omittableOpaqueAttachmentPatternIndex?: number | null
  isolateCustomPatterns?: boolean
  workerFactory?: SecretRedactionWorkerFactory
  workerTimeoutMs?: number
}): SecretRedactor {
  if (
    !Array.isArray(options.patterns) ||
    options.patterns.length > MAX_PATTERN_COUNT
  ) {
    throw new SecretRedactionError("invalid_pattern")
  }
  const patterns = options.patterns.map(compilePattern)
  const totalPatternBytes = patterns.reduce(
    (total, pattern) => total + utf8ByteLength(pattern.source),
    0,
  )
  if (totalPatternBytes > MAX_PATTERN_TOTAL_BYTES) {
    throw new SecretRedactionError("invalid_pattern")
  }
  const usesIsolatedPatterns =
    options.isolateCustomPatterns === true &&
    !matchesDefaultPatternProfile(patterns)
  validateRedactionToken(
    options.redactionToken,
    patterns,
    !usesIsolatedPatterns,
  )
  const redactionToken = options.redactionToken
  const workerFactory = options.workerFactory ?? defaultPatternWorkerFactory
  const workerTimeoutMs = Number.isFinite(options.workerTimeoutMs)
    ? Math.max(1, Math.floor(options.workerTimeoutMs as number))
    : DEFAULT_PATTERN_WORKER_TIMEOUT_MS
  const omittableOpaqueAttachmentPatternIndex = Number.isInteger(
    options.omittableOpaqueAttachmentPatternIndex,
  )
    ? (options.omittableOpaqueAttachmentPatternIndex as number)
    : null
  const limits = {
    maxDepth: normalizedLimit(options.limits.maxDepth, 12),
    maxNodes: normalizedLimit(options.limits.maxNodes, 20_000),
    maxChars: normalizedLimit(options.limits.maxChars, 2 * 1024 * 1024),
  }
  const providerMaxNodes = normalizedLimit(
    options.providerLimits?.maxNodes ?? 0,
    1_000_000,
  )
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
      normalizedLimit(
        options.providerLimits?.maxMessageChars ?? 0,
        16 * 1024 * 1024,
      ),
      providerMaxChars,
    ),
  }

  function createBudget(maxNodes: number, maxChars: number): ResourceBudget {
    return { nodes: 0, chars: 0, maxNodes, maxChars }
  }

  function chargeNode(
    state: TraversalState,
    localBudget?: ResourceBudget,
  ): void {
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
    chargeCharCount(text.length, budget, localBudget)
  }

  function chargeCharCount(
    count: number,
    budget: ResourceBudget,
    localBudget?: ResourceBudget,
  ): void {
    budget.chars += count
    if (budget.chars > budget.maxChars) {
      throw new SecretRedactionError("text_limit")
    }
    if (localBudget) {
      localBudget.chars += count
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
    applicationOptions: PatternApplicationOptions = {},
  ): PatternApplication {
    const shouldCharge = applicationOptions.charge !== false
    if (applicationOptions.batch) {
      const batch = applicationOptions.batch
      if (
        shouldCharge &&
        (text.length > budget.maxChars - budget.chars ||
          (localBudget &&
            text.length > localBudget.maxChars - localBudget.chars))
      ) {
        throw new SecretRedactionError("text_limit")
      }
      const operationIndex = queuePatternOperation(batch, {
        operationIndex: batch.operations.length,
        kind: "apply",
        text,
        inputOperationIndex: applicationOptions.inputOperationIndex ?? null,
      })
      queuePatternAction(batch, operationIndex, (result, context) => {
        if (result.kind !== "apply") {
          throw new SecretRedactionError("unexpected_failure")
        }
        const materialized = materializeApplyResult({
          result,
          batch,
          patterns,
          redactionToken,
          context,
        })
        if (shouldCharge) {
          chargeCharCount(materialized.inputLength, budget, localBudget)
          if (materialized.positiveExpansion > 0) {
            chargeCharCount(materialized.positiveExpansion, budget, localBudget)
          }
        }
        stats.scannedChars += materialized.inputLength
        stats.matches += materialized.matchCount
        applicationOptions.onDeferred?.(result, materialized)
      })
      return {
        text,
        firstPatternIndex: null,
        deferredOperationIndex: operationIndex,
      }
    }
    if (shouldCharge) {
      chargeChars(text, budget, localBudget)
    }
    stats.scannedChars += text.length
    let next = text
    let firstPatternIndex: number | null = null
    for (const [patternIndex, pattern] of patterns.entries()) {
      const regex = new RegExp(pattern.source, pattern.flags)
      next = next.replace(regex, (match) => {
        if (shouldCharge) {
          const expansion = redactionToken.length - match.length
          if (expansion > 0) {
            chargeCharCount(expansion, budget, localBudget)
          }
        }
        firstPatternIndex ??= patternIndex
        stats.matches += 1
        return redactionToken
      })
    }
    if (
      firstPatternIndex !== null &&
      firstPatternMatch(next, patterns) !== null
    ) {
      throw new SecretRedactionError("unexpected_failure")
    }
    return { text: next, firstPatternIndex, deferredOperationIndex: null }
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
      locationCode: locationCode(
        options.key,
        options.parentKey,
        options.grandparentKey,
      ),
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
    if (
      !part ||
      typeof part !== "object" ||
      ownDataValue(part, "type") !== "reasoning"
    ) {
      return false
    }
    const metadata = ownDataRecord(part, "metadata")
    const openai = ownDataRecord(metadata, "openai")
    const itemId = ownDataValue(openai, "itemId")
    const validItemId =
      itemId === MISSING_OWN_VALUE ||
      (typeof itemId === "string" && /^rs_.+$/.test(itemId))
    return (
      Boolean(openai) &&
      parent === openai &&
      validItemId &&
      ownDataValue(openai, "reasoningEncryptedContent") === value
    )
  }

  function qualifiedOpenAIAttachmentMime(options: {
    messageRoot: unknown
    parent: Record<string, unknown> | unknown[] | null
    key: string | number | null
    path: PropertyPath
    value: string
  }): string | null {
    const { messageRoot, parent, key, path, value } = options
    if (
      key !== "url" ||
      path.length !== 6 ||
      path[0] !== "parts" ||
      !Number.isInteger(path[1]) ||
      path[2] !== "state" ||
      path[3] !== "attachments" ||
      !Number.isInteger(path[4]) ||
      path[5] !== "url"
    ) {
      return null
    }

    const info = ownDataRecord(messageRoot, "info")
    const parts = ownDataValue(messageRoot, "parts")
    const partIndex = path[1] as number
    const attachmentIndex = path[4] as number
    if (
      !info ||
      ownDataValue(info, "role") !== "assistant" ||
      ownDataValue(info, "providerID") !== "openai" ||
      !Array.isArray(parts) ||
      partIndex < 0 ||
      partIndex >= parts.length
    ) {
      return null
    }

    const messageId = ownDataValue(info, "id")
    const sessionId = ownDataValue(info, "sessionID")
    const part = ownDataValue(parts, partIndex)
    if (
      typeof messageId !== "string" ||
      !messageId ||
      typeof sessionId !== "string" ||
      !sessionId ||
      !part ||
      typeof part !== "object" ||
      Array.isArray(part) ||
      ownDataValue(part, "type") !== "tool" ||
      typeof ownDataValue(part, "tool") !== "string" ||
      !(ownDataValue(part, "tool") as string) ||
      typeof ownDataValue(part, "callID") !== "string" ||
      !(ownDataValue(part, "callID") as string) ||
      typeof ownDataValue(part, "id") !== "string" ||
      !(ownDataValue(part, "id") as string) ||
      ownDataValue(part, "messageID") !== messageId ||
      ownDataValue(part, "sessionID") !== sessionId
    ) {
      return null
    }

    const state = ownDataRecord(part, "state")
    const attachments = ownDataValue(state, "attachments")
    const stateTime = ownDataRecord(state, "time")
    if (
      !state ||
      ownDataValue(state, "status") !== "completed" ||
      !stateTime ||
      ownDataValue(stateTime, "compacted") !== MISSING_OWN_VALUE ||
      "compacted" in stateTime ||
      !Array.isArray(attachments) ||
      attachmentIndex < 0 ||
      attachmentIndex >= attachments.length
    ) {
      return null
    }
    const attachment = ownDataValue(attachments, attachmentIndex)
    const mime = ownDataValue(attachment, "mime")
    return Boolean(attachment) &&
      typeof attachment === "object" &&
      !Array.isArray(attachment) &&
      parent === attachment &&
      ownDataValue(attachment, "type") === "file" &&
      typeof mime === "string" &&
      mime.length > 0 &&
      typeof ownDataValue(attachment, "id") === "string" &&
      Boolean(ownDataValue(attachment, "id")) &&
      typeof ownDataValue(attachment, "messageID") === "string" &&
      Boolean(ownDataValue(attachment, "messageID")) &&
      typeof ownDataValue(attachment, "sessionID") === "string" &&
      Boolean(ownDataValue(attachment, "sessionID")) &&
      ownDataValue(attachment, "url") === value
      ? mime
      : null
  }

  function qualifiedDirectUserFileMime(options: {
    messageRoot: unknown
    parent: Record<string, unknown> | unknown[] | null
    key: string | number | null
    path: PropertyPath
    value: string
  }): string | null {
    const { messageRoot, parent, key, path, value } = options
    if (
      key !== "url" ||
      path.length !== 3 ||
      path[0] !== "parts" ||
      !Number.isInteger(path[1]) ||
      path[2] !== "url"
    ) {
      return null
    }

    const info = ownDataRecord(messageRoot, "info")
    const parts = ownDataValue(messageRoot, "parts")
    const partIndex = path[1] as number
    if (
      !info ||
      ownDataValue(info, "role") !== "user" ||
      !Array.isArray(parts) ||
      partIndex < 0 ||
      partIndex >= parts.length
    ) {
      return null
    }

    const messageId = ownDataValue(info, "id")
    const sessionId = ownDataValue(info, "sessionID")
    const part = ownDataValue(parts, partIndex)
    const mime = ownDataValue(part, "mime")
    return typeof messageId === "string" &&
      messageId.length > 0 &&
      typeof sessionId === "string" &&
      sessionId.length > 0 &&
      Boolean(part) &&
      typeof part === "object" &&
      !Array.isArray(part) &&
      parent === part &&
      ownDataValue(part, "type") === "file" &&
      typeof ownDataValue(part, "id") === "string" &&
      Boolean(ownDataValue(part, "id")) &&
      ownDataValue(part, "messageID") === messageId &&
      ownDataValue(part, "sessionID") === sessionId &&
      typeof mime === "string" &&
      mime.length > 0 &&
      ownDataValue(part, "url") === value
      ? mime
      : null
  }

  function isOmittableOpaqueAttachmentPattern(
    pattern: CompiledPattern,
  ): boolean {
    return (
      pattern.index === omittableOpaqueAttachmentPatternIndex &&
      isLinearOpaqueAttachmentPattern(pattern)
    )
  }

  function opaqueAttachmentCollisionCount(value: string): number {
    let count = 0
    for (const pattern of patterns) {
      if (!isOmittableOpaqueAttachmentPattern(pattern)) continue
      for (const match of opaqueAttachmentPatternMatches(value)) {
        count += match.end > match.start ? 1 : 0
      }
    }
    return count
  }

  function scanQualifiedOpaqueAttachment(options: {
    value: string
    payloadStart: number | null
    payloadEnd: number | null
    stats: SecretRedactionStats
    budget: ResourceBudget
    localBudget?: ResourceBudget
    batch?: PatternBatch | null
    inputOperationIndex?: number | null
    onDeferred?: (
      result: PatternWorkerAttachmentResult,
      inputText: string,
    ) => void
  }): PatternScanResult {
    const { value, payloadStart, payloadEnd, stats, budget, localBudget } =
      options
    if (options.batch) {
      const batch = options.batch
      const operationIndex = queuePatternOperation(batch, {
        operationIndex: batch.operations.length,
        kind: "attachment",
        text: value,
        payloadStart,
        payloadEnd,
        omittablePatternIndex: omittableOpaqueAttachmentPatternIndex,
        inputOperationIndex: options.inputOperationIndex ?? null,
      })
      queuePatternAction(batch, operationIndex, (result, context) => {
        if (result.kind !== "attachment") {
          throw new SecretRedactionError("unexpected_failure")
        }
        const materialized = materializeAttachmentResult({
          result,
          batch,
          patterns,
          context,
        })
        chargeCharCount(materialized.inputText.length, budget, localBudget)
        stats.scannedChars += materialized.inputText.length
        if (materialized.blockingPatternIndex === null) {
          stats.omittedOpaqueAttachmentMatches += materialized.omittedMatchCount
        } else {
          stats.matches += 1
        }
        options.onDeferred?.(result, materialized.inputText)
      })
      return {
        blockingPatternIndex: null,
        deferredOperationIndex: operationIndex,
      }
    }
    chargeChars(value, budget, localBudget)
    stats.scannedChars += value.length
    let omittedMatches = 0
    for (const pattern of patterns) {
      if (isLinearOpaqueAttachmentPattern(pattern)) {
        for (const match of opaqueAttachmentPatternMatches(value)) {
          if (
            isOmittableOpaqueAttachmentPattern(pattern) &&
            payloadStart !== null &&
            payloadEnd !== null &&
            match.start >= payloadStart &&
            match.end <= payloadEnd
          ) {
            omittedMatches += 1
          } else {
            stats.matches += 1
            return {
              blockingPatternIndex: pattern.index,
              deferredOperationIndex: null,
            }
          }
        }
        continue
      }
      const regex = new RegExp(pattern.source, pattern.flags)
      for (let match = regex.exec(value); match; match = regex.exec(value)) {
        const start = match.index
        const end = start + match[0].length
        if (
          isOmittableOpaqueAttachmentPattern(pattern) &&
          payloadStart !== null &&
          payloadEnd !== null &&
          start >= payloadStart &&
          end <= payloadEnd
        ) {
          omittedMatches += 1
        } else {
          stats.matches += 1
          return {
            blockingPatternIndex: pattern.index,
            deferredOperationIndex: null,
          }
        }
        if (match[0].length === 0) regex.lastIndex += 1
      }
    }
    stats.omittedOpaqueAttachmentMatches += omittedMatches
    return { blockingPatternIndex: null, deferredOperationIndex: null }
  }

  function canChargeChars(
    value: string,
    budget: ResourceBudget,
    localBudget?: ResourceBudget,
  ): boolean {
    return (
      value.length <= budget.maxChars - budget.chars &&
      (!localBudget || value.length <= localBudget.maxChars - localBudget.chars)
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
    if (
      status === "completed" ||
      status === "pending" ||
      status === "running"
    ) {
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
    if (parentMode === "immutable-scan") {
      return "immutable-scan"
    }
    if (IMMUTABLE_PROTOCOL_KEYS.has(key)) {
      return "immutable-scan"
    }
    if (MUTABLE_CONTENT_KEYS.has(key)) {
      return "redact"
    }
    return parentMode
  }

  function createTraversalState(
    traversalLimits: SecretRedactionLimits,
    revisitAliases: boolean,
    strictProviderObjects = false,
    patternBatch: PatternBatch | null = null,
  ): TraversalState {
    if (strictProviderObjects) {
      const prototypeKeys = Reflect.ownKeys(Object.prototype)
      if (
        prototypeKeys.length !== STANDARD_OBJECT_PROTOTYPE_KEYS.size ||
        prototypeKeys.some((key) => !STANDARD_OBJECT_PROTOTYPE_KEYS.has(key))
      ) {
        throw new SecretRedactionError("malformed_provider_object")
      }
    }
    return {
      stats: emptyStats(),
      budget: createBudget(traversalLimits.maxNodes, traversalLimits.maxChars),
      maxDepth: traversalLimits.maxDepth,
      active: new WeakSet<object>(),
      visited: new WeakSet<object>(),
      revisitAliases,
      strictProviderObjects,
      patternBatch,
    }
  }

  function providerOwnDataChildren(
    value: object,
    maxChildren: number,
  ): Array<[string | number, unknown]> {
    if (isProxy(value)) {
      throw new SecretRedactionError("malformed_provider_object")
    }
    const prototype = Object.getPrototypeOf(value)
    const isArray = Array.isArray(value)
    if (
      (isArray && prototype !== Array.prototype) ||
      (!isArray && prototype !== Object.prototype && prototype !== null)
    ) {
      throw new SecretRedactionError("malformed_provider_object")
    }

    const ownKeys = Reflect.ownKeys(value)
    if (isArray) {
      const array = value as unknown[]
      if (array.length > maxChildren || ownKeys.length !== array.length + 1) {
        throw new SecretRedactionError(
          array.length > maxChildren
            ? "node_limit"
            : "malformed_provider_object",
        )
      }
      const children: Array<[number, unknown]> = []
      for (let index = 0; index < array.length; index += 1) {
        const descriptor = Object.getOwnPropertyDescriptor(array, String(index))
        if (!descriptor || !("value" in descriptor) || !descriptor.enumerable) {
          throw new SecretRedactionError("malformed_provider_object")
        }
        children.push([index, descriptor.value])
      }
      const lengthDescriptor = Object.getOwnPropertyDescriptor(array, "length")
      if (
        !lengthDescriptor ||
        !("value" in lengthDescriptor) ||
        lengthDescriptor.value !== array.length ||
        ownKeys.some(
          (key) =>
            typeof key !== "string" ||
            (key !== "length" &&
              (!/^(?:0|[1-9][0-9]*)$/.test(key) ||
                Number(key) >= array.length)),
        )
      ) {
        throw new SecretRedactionError("malformed_provider_object")
      }
      return children
    }

    if (ownKeys.length > maxChildren) {
      throw new SecretRedactionError("node_limit")
    }
    const children: Array<[string, unknown]> = []
    for (const childKey of ownKeys) {
      if (typeof childKey !== "string") {
        throw new SecretRedactionError("malformed_provider_object")
      }
      const descriptor = Object.getOwnPropertyDescriptor(value, childKey)
      if (!descriptor || !("value" in descriptor) || !descriptor.enumerable) {
        throw new SecretRedactionError("malformed_provider_object")
      }
      children.push([childKey, descriptor.value])
    }
    return children
  }

  function remainingNodeBudget(
    state: TraversalState,
    localBudget?: ResourceBudget,
  ): number {
    return Math.min(
      state.budget.maxNodes - state.budget.nodes,
      localBudget
        ? localBudget.maxNodes - localBudget.nodes
        : Number.POSITIVE_INFINITY,
    )
  }

  function previousApplyOperation(
    batch: PatternBatch | null,
    parent: Record<string, unknown> | unknown[] | null,
    key: string | number | null,
  ): number | null {
    if (!batch || parent === null || key === null) return null
    return batch.lastApplyOperations.get(parent)?.get(key) ?? null
  }

  function rememberApplyOperation(
    batch: PatternBatch | null,
    parent: Record<string, unknown> | unknown[] | null,
    key: string | number | null,
    operationIndex: number,
  ): void {
    if (!batch || parent === null || key === null) return
    let target = batch.lastApplyOperations.get(parent)
    if (!target) {
      target = new Map<PropertyKey, number>()
      batch.lastApplyOperations.set(parent, target)
    }
    target.set(key, operationIndex)
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

    if (
      state.strictProviderObjects &&
      (value === undefined ||
        typeof value === "function" ||
        typeof value === "symbol" ||
        typeof value === "bigint" ||
        (typeof value === "number" && !Number.isFinite(value)))
    ) {
      throw new SecretRedactionError("malformed_provider_object")
    }

    if (typeof value === "string") {
      const inputOperationIndex = previousApplyOperation(
        state.patternBatch,
        parent,
        key,
      )
      if (
        messageRoot !== undefined &&
        isTrustedOpenAIReasoningCiphertext({
          messageRoot,
          parent,
          key,
          path,
          value,
        })
      ) {
        chargeChars(value, state.budget, localBudget)
        return
      }
      if (messageRoot !== undefined) {
        const mime =
          qualifiedDirectUserFileMime({
            messageRoot,
            parent,
            key,
            path,
            value,
          }) ??
          qualifiedOpenAIAttachmentMime({
            messageRoot,
            parent,
            key,
            path,
            value,
          })
        if (mime && canChargeChars(value, state.budget, localBudget)) {
          const omittedCollisionCount = opaqueAttachmentCollisionCount(value)
          const envelope =
            omittedCollisionCount > 0
              ? parseCanonicalProviderAttachmentDataUrl(value, mime)
              : null
          if (envelope || patterns.some(isLinearOpaqueAttachmentPattern)) {
            const blockingPatternIndex = scanQualifiedOpaqueAttachment({
              value,
              payloadStart: envelope?.payloadStart ?? null,
              payloadEnd: envelope?.payloadEnd ?? null,
              stats: state.stats,
              budget: state.budget,
              localBudget,
              batch: state.patternBatch,
              inputOperationIndex,
              onDeferred: (result) => {
                if (result.blockingPatternIndex !== null) {
                  throw immutableMatchError({
                    matchTarget: "value",
                    patternIndex: result.blockingPatternIndex,
                    key,
                    parentKey,
                    grandparentKey,
                  })
                }
              },
            })
            if (blockingPatternIndex.deferredOperationIndex !== null) return
            if (blockingPatternIndex.blockingPatternIndex === null) return
            throw immutableMatchError({
              matchTarget: "value",
              patternIndex: blockingPatternIndex.blockingPatternIndex,
              key,
              parentKey,
              grandparentKey,
            })
          }
        }
      }
      const applied = applyPatterns(
        value,
        state.stats,
        state.budget,
        localBudget,
        {
          batch: state.patternBatch,
          inputOperationIndex,
          onDeferred: (_result, materialized) => {
            if (materialized.residualPatternIndex !== null) {
              throw new SecretRedactionError("unexpected_failure")
            }
            if (materialized.text === value) return
            if (mode !== "redact") {
              throw immutableMatchError({
                matchTarget: "value",
                patternIndex: materialized.firstPatternIndex,
                key,
                parentKey,
                grandparentKey,
              })
            }
            schedulePatternAssignment(
              state.patternBatch as PatternBatch,
              parent,
              key,
              materialized.inputText,
              materialized.text,
            )
            state.stats.redactedFields += 1
          },
        },
      )
      if (applied.deferredOperationIndex !== null) {
        rememberApplyOperation(
          state.patternBatch,
          parent,
          key,
          applied.deferredOperationIndex,
        )
        return
      }
      if (applied.text === value) {
        return
      }
      if (mode !== "redact") {
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
    const strictChildren =
      state.strictProviderObjects && value && typeof value === "object"
        ? providerOwnDataChildren(
            value,
            remainingNodeBudget(state, localBudget),
          )
        : null
    if (state.patternBatch && value && typeof value === "object") {
      capturePatternBatchSnapshot(state.patternBatch, value)
    }
    if (messageRoot !== undefined) {
      const projection = toolStateMetadataProjection({
        messageRoot,
        parent,
        path,
        value,
      })
      if (projection) {
        if (projection.kind === "output") {
          const outputKey = "output"
          const keyProbe = applyPatterns(
            outputKey,
            state.stats,
            state.budget,
            localBudget,
            {
              batch: state.patternBatch,
              onDeferred: (_result, materialized) => {
                if (materialized.residualPatternIndex !== null) {
                  throw new SecretRedactionError("unexpected_failure")
                }
                if (materialized.text !== outputKey) {
                  throw immutableMatchError({
                    matchTarget: "key",
                    patternIndex: materialized.firstPatternIndex,
                    key: outputKey,
                    parentKey: key,
                    grandparentKey: parentKey,
                  })
                }
              },
            },
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
    const isolatedChildren =
      state.patternBatch && !strictChildren
        ? isolatedOwnDataChildren(value)
        : null
    if (state.active.has(value)) {
      throw new SecretRedactionError("cycle_detected")
    }
    if (!state.revisitAliases && state.visited.has(value)) {
      return
    }
    state.active.add(value)

    if (Array.isArray(value)) {
      if (strictChildren ?? isolatedChildren) {
        for (const [index, child] of strictChildren ?? isolatedChildren ?? []) {
          visit(
            child,
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
      }
    } else {
      const record = value as Record<string, unknown>
      const children =
        strictChildren ??
        isolatedChildren ??
        Object.keys(record).map(
          (childKey) => [childKey, record[childKey]] as [string, unknown],
        )
      for (const [childKey, child] of children) {
        if (typeof childKey !== "string") {
          throw new SecretRedactionError("malformed_provider_object")
        }
        const keyProbe = applyPatterns(
          childKey,
          state.stats,
          state.budget,
          localBudget,
          {
            batch: state.patternBatch,
            onDeferred: (_result, materialized) => {
              if (materialized.residualPatternIndex !== null) {
                throw new SecretRedactionError("unexpected_failure")
              }
              if (materialized.text !== childKey) {
                throw immutableMatchError({
                  matchTarget: "key",
                  patternIndex: materialized.firstPatternIndex,
                  key: childKey,
                  parentKey: key,
                  grandparentKey: parentKey,
                })
              }
            },
          },
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
          child,
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

  function traverse(
    root: unknown,
    initialMode: VisitMode,
    strictProviderObjects = false,
  ): SecretRedactionStats {
    const state = createTraversalState(limits, false, strictProviderObjects)
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
    if (!Array.isArray(messages) || isProxy(messages)) {
      throw new SecretRedactionError("malformed_provider_object")
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
      true,
    )
    try {
      chargeNode(state)
      const messageEntries = providerOwnDataChildren(
        messages,
        state.budget.maxNodes - state.budget.nodes,
      )
      state.active.add(messages)
      for (const [index, message] of messageEntries) {
        const localBudget = createBudget(
          limits.maxNodes,
          providerLimits.maxMessageChars,
        )
        visit(
          message,
          messages,
          index,
          "root-scan",
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

  function traverseProviderSystem(system: unknown): SecretRedactionStats {
    if (!Array.isArray(system) || isProxy(system)) {
      throw new SecretRedactionError("malformed_provider_object")
    }
    const state = createTraversalState(limits, false, true)
    try {
      chargeNode(state)
      const systemEntries = providerOwnDataChildren(
        system,
        state.budget.maxNodes - state.budget.nodes,
      )
      state.active.add(system)
      for (const [index, entry] of systemEntries) {
        visit(
          entry,
          system,
          index,
          typeof entry === "string" ? "redact" : "root-scan",
          1,
          null,
          null,
          [index],
          state,
        )
      }
      state.active.delete(system)
      state.visited.add(system)
      return state.stats
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("unexpected_failure")
    }
  }

  function queueTokenValidation(batch: PatternBatch): void {
    const operationIndex = queuePatternOperation(batch, {
      operationIndex: batch.operations.length,
      kind: "match",
      text: redactionToken,
    })
    queuePatternAction(batch, operationIndex, (result) => {
      if (result.kind !== "match") {
        throw new SecretRedactionError("unexpected_failure")
      }
      if (materializeMatchResult(result, patterns) !== null) {
        throw new SecretRedactionError("invalid_redaction_token")
      }
    })
  }

  async function traverseIsolated(
    root: unknown,
    initialMode: VisitMode,
    strictProviderObjects = false,
  ): Promise<SecretRedactionStats> {
    const batch = createPatternBatch()
    const state = createTraversalState(
      limits,
      false,
      strictProviderObjects,
      batch,
    )
    try {
      queueTokenValidation(batch)
      visit(root, null, null, initialMode, 0, null, null, [], state)
      await executePatternBatch({
        batch,
        patterns,
        redactionToken,
        workerFactory,
        timeoutMs: workerTimeoutMs,
      })
      return state.stats
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("unexpected_failure")
    }
  }

  async function traverseProviderMessagesIsolated(
    messages: unknown,
  ): Promise<SecretRedactionStats> {
    if (!Array.isArray(messages) || isProxy(messages)) {
      throw new SecretRedactionError("malformed_provider_object")
    }
    if (messages.length > providerLimits.maxMessages) {
      throw new SecretRedactionError("node_limit")
    }
    const batch = createPatternBatch()
    const state = createTraversalState(
      {
        maxDepth: limits.maxDepth,
        maxNodes: providerLimits.maxNodes,
        maxChars: providerLimits.maxChars,
      },
      true,
      true,
      batch,
    )
    try {
      queueTokenValidation(batch)
      chargeNode(state)
      const messageEntries = providerOwnDataChildren(
        messages,
        state.budget.maxNodes - state.budget.nodes,
      )
      capturePatternBatchSnapshot(batch, messages)
      state.active.add(messages)
      for (const [index, message] of messageEntries) {
        const localBudget = createBudget(
          limits.maxNodes,
          providerLimits.maxMessageChars,
        )
        visit(
          message,
          messages,
          index,
          "root-scan",
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
      await executePatternBatch({
        batch,
        patterns,
        redactionToken,
        workerFactory,
        timeoutMs: workerTimeoutMs,
      })
      return state.stats
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("unexpected_failure")
    }
  }

  async function traverseProviderSystemIsolated(
    system: unknown,
  ): Promise<SecretRedactionStats> {
    if (!Array.isArray(system) || isProxy(system)) {
      throw new SecretRedactionError("malformed_provider_object")
    }
    const batch = createPatternBatch()
    const state = createTraversalState(limits, false, true, batch)
    try {
      queueTokenValidation(batch)
      chargeNode(state)
      const systemEntries = providerOwnDataChildren(
        system,
        state.budget.maxNodes - state.budget.nodes,
      )
      capturePatternBatchSnapshot(batch, system)
      state.active.add(system)
      for (const [index, entry] of systemEntries) {
        visit(
          entry,
          system,
          index,
          typeof entry === "string" ? "redact" : "root-scan",
          1,
          null,
          null,
          [index],
          state,
        )
      }
      state.active.delete(system)
      state.visited.add(system)
      await executePatternBatch({
        batch,
        patterns,
        redactionToken,
        workerFactory,
        timeoutMs: workerTimeoutMs,
      })
      return state.stats
    } catch (error) {
      if (error instanceof SecretRedactionError) {
        throw error
      }
      throw new SecretRedactionError("unexpected_failure")
    }
  }

  async function redactTextIsolated(
    text: string,
  ): Promise<{ text: string; stats: SecretRedactionStats }> {
    const batch = createPatternBatch()
    const stats = emptyStats()
    const budget = createBudget(limits.maxNodes, limits.maxChars)
    let redactedText = text
    queueTokenValidation(batch)
    const applied = applyPatterns(text, stats, budget, undefined, {
      batch,
      onDeferred: (_result, materialized) => {
        if (materialized.residualPatternIndex !== null) {
          throw new SecretRedactionError("unexpected_failure")
        }
        redactedText = materialized.text
        if (materialized.text !== text) {
          stats.redactedFields = 1
        }
      },
    })
    if (applied.deferredOperationIndex === null) {
      throw new SecretRedactionError("unexpected_failure")
    }
    await executePatternBatch({
      batch,
      patterns,
      redactionToken,
      workerFactory,
      timeoutMs: workerTimeoutMs,
    })
    return { text: redactedText, stats }
  }

  return {
    usesIsolatedPatterns,
    redactText(text: string): { text: string; stats: SecretRedactionStats } {
      if (usesIsolatedPatterns) {
        throw new SecretRedactionError("unexpected_failure")
      }
      const stats = emptyStats()
      const budget = createBudget(limits.maxNodes, limits.maxChars)
      const redacted = applyPatterns(text, stats, budget)
      if (redacted.text !== text) {
        stats.redactedFields = 1
      }
      return { text: redacted.text, stats }
    },
    redactMutableValue(value: unknown): SecretRedactionStats {
      if (usesIsolatedPatterns) {
        throw new SecretRedactionError("unexpected_failure")
      }
      return traverse(value, "redact")
    },
    redactProviderMessages(messages: unknown): SecretRedactionStats {
      if (usesIsolatedPatterns) {
        throw new SecretRedactionError("unexpected_failure")
      }
      return traverseProviderMessages(messages)
    },
    redactProviderSystem(system: unknown): SecretRedactionStats {
      if (usesIsolatedPatterns) {
        throw new SecretRedactionError("unexpected_failure")
      }
      return traverseProviderSystem(system)
    },
    async redactTextAsync(text: string): Promise<{
      text: string
      stats: SecretRedactionStats
    }> {
      if (!usesIsolatedPatterns) {
        return this.redactText(text)
      }
      return redactTextIsolated(text)
    },
    async redactMutableValueAsync(
      value: unknown,
    ): Promise<SecretRedactionStats> {
      if (!usesIsolatedPatterns) {
        return this.redactMutableValue(value)
      }
      return traverseIsolated(value, "redact")
    },
    async redactProviderMessagesAsync(
      messages: unknown,
    ): Promise<SecretRedactionStats> {
      if (!usesIsolatedPatterns) {
        return this.redactProviderMessages(messages)
      }
      return traverseProviderMessagesIsolated(messages)
    },
    async redactProviderSystemAsync(
      system: unknown,
    ): Promise<SecretRedactionStats> {
      if (!usesIsolatedPatterns) {
        return this.redactProviderSystem(system)
      }
      return traverseProviderSystemIsolated(system)
    },
  }
}
