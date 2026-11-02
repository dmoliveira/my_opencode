export type TaskerSandbox = Readonly<{
  scope: string
  worktree: string
  branch: string
}>
export type TaskerCommandContext = Readonly<{
  sessionID?: string
  sandbox?: TaskerSandbox
  knownRecordIds?: ReadonlySet<string>
  knownRecordTargets?: ReadonlyMap<string, TaskerSandbox>
}>
export type TaskerCommandInspection = Readonly<{
  kind: "read" | "write"
  verb: string
  positionals: readonly string[]
  options: Readonly<Record<string, readonly string[]>>
  json: boolean
}>
type ParsedOptions = { positionals: string[]; values: Map<string, string[]> }
const ADD_TYPES = new Set(["task", "epic", "memory", "doc"])
const READ_TYPES = new Set([...ADD_TYPES, "event", "link", "session"])
const READ_VERBS = new Set(["current", "next", "queue"])
const SET_FIELDS = new Set(["goal", "kind", "priority", "summary", "title"])
const RECORD_ID = /^(?:task|epic|memory|doc|event|link|session)_\d+$/
const READ_OPTIONS = new Set([
  "--kind",
  "--label",
  "--limit",
  "--priority",
  "--scope",
  "--since",
  "--status",
  "--type",
  "--until",
  "--view",
])
const ADD_OPTIONS = new Set([
  "--actor",
  "--branch",
  "--body",
  "--goal",
  "--kind",
  "--label",
  "--priority",
  "--ref",
  "--request-id",
  "--scope",
  "--summary",
  "--type",
  "--worktree",
])
const REPAIR_OPTIONS = new Set([
  "--actor",
  "--expected-revision",
  "--reason",
  "--request-id",
])
const LINK_OPTIONS = new Set(["--actor", "--request-id"])

export function isPlanningLink(
  source: string,
  relation: string,
  target: string,
): boolean {
  return (
    (/^epic_\d+$/.test(source) &&
      relation === "parent-of" &&
      /^task_\d+$/.test(target)) ||
    (/^task_\d+$/.test(source) &&
      relation === "depends-on" &&
      /^task_\d+$/.test(target) &&
      source !== target) ||
    (/^memory_\d+$/.test(source) &&
      relation === "about" &&
      /^(?:task|epic|doc)_\d+$/.test(target))
  )
}
export function taskerOption(
  command: TaskerCommandInspection,
  name: string,
): string | undefined {
  return command.options[name]?.[0]
}
function splitOptions(
  args: string[],
  allowed: Set<string>,
): ParsedOptions | null {
  const positionals: string[] = []
  const values = new Map<string, string[]>()
  for (let index = 0; index < args.length; index += 1) {
    const token = args[index]
    if (!token.startsWith("--")) {
      positionals.push(token)
      continue
    }
    const equals = token.indexOf("=")
    const name = equals < 0 ? token : token.slice(0, equals)
    if (!allowed.has(name)) return null
    const value = equals < 0 ? args[++index] : token.slice(equals + 1)
    if (
      !value ||
      value.startsWith("--") ||
      value.length > 4096 ||
      /[\0\r\n]/.test(value)
    )
      return null
    const previous = values.get(name) ?? []
    if (previous.length && name !== "--label") return null
    values.set(name, [...previous, value])
  }
  return { positionals, values }
}
function parseShell(command: string, sessionID?: string): string[] | null {
  if (!command || command.length > 16384 || /[\0\r\n$`\\]/.test(command))
    return null
  const tokens: string[] = []
  let token = "",
    started = false
  let quote: "'" | '"' | null = null
  const flush = (): void => {
    if (started) tokens.push(token)
    token = ""
    started = false
  }
  for (const char of command) {
    if (quote) {
      if (char === quote) quote = null
      else token += char
      started = true
      continue
    }
    if (char === "'" || char === '"') {
      quote = char
      started = true
      continue
    }
    if (/\s/.test(char)) {
      flush()
      continue
    }
    if (/[;&|<>(){}[\]#~*?]/.test(char)) return null
    token += char
    started = true
  }
  if (quote) return null
  flush()
  if (tokens[0]?.startsWith("OPENCODE_SESSION_ID=")) {
    if (!sessionID || tokens[0] !== `OPENCODE_SESSION_ID=${sessionID}`)
      return null
    tokens.shift()
  }
  return tokens.length > 0 && tokens.length <= 96 ? tokens : null
}
function normalize(
  segment: string[],
): { args: string[]; json: boolean } | null {
  if (segment[0] !== "oc") return null
  const args = ["oc"]
  let json = false
  for (let index = 1; index < segment.length; index += 1) {
    const token = segment[index]
    if (token === "--config" || token.startsWith("--config=")) return null
    if (token === "--format" || token.startsWith("--format=")) {
      const value = token === "--format" ? segment[++index] : token.slice(9)
      if (json || value !== "json") return null
      json = true
    } else args.push(token)
  }
  return { args, json }
}
function known(context: TaskerCommandContext, id: string): boolean {
  if (context.knownRecordTargets && context.sandbox) {
    const target = context.knownRecordTargets.get(id)
    return (
      target?.scope === context.sandbox.scope &&
      target.worktree === context.sandbox.worktree &&
      target.branch === context.sandbox.branch
    )
  }
  return context.knownRecordIds?.has(id) === true
}
function scopeMatches(
  parsed: ParsedOptions,
  context: TaskerCommandContext,
  required = false,
): boolean {
  const value = parsed.values.get("--scope")?.[0]
  return (
    (!required || Boolean(value)) &&
    (!context.sandbox || !value || value === context.sandbox.scope)
  )
}
function make(
  verb: string,
  kind: "read" | "write",
  parsed: ParsedOptions,
  json: boolean,
): TaskerCommandInspection {
  return {
    verb,
    kind,
    positionals: parsed.positionals,
    options: Object.fromEntries(parsed.values),
    json,
  }
}
function inspect(
  args: string[],
  json: boolean,
  context: TaskerCommandContext,
): TaskerCommandInspection | null {
  const verb = args[1] ?? ""
  const simple = (
    kind: "read" | "write",
    positionals: string[] = [],
  ): TaskerCommandInspection => ({ verb, kind, positionals, options: {}, json })
  if (verb === "config")
    return args.length === 3 && args[2] === "--doctor" ? simple("read") : null
  if (verb === "--help") return args.length === 2 ? simple("read") : null
  if (verb === "help")
    return args.length <= 3 ? simple("read", args.slice(2)) : null
  if (READ_VERBS.has(verb)) {
    const p = splitOptions(args.slice(2), READ_OPTIONS)
    return p && !p.positionals.length && scopeMatches(p, context)
      ? make(verb, "read", p, json)
      : null
  }
  if (verb === "find") {
    const p = splitOptions(args.slice(2), READ_OPTIONS)
    return p &&
      p.positionals.length === 1 &&
      READ_TYPES.has(p.values.get("--type")?.[0] ?? "") &&
      scopeMatches(p, context, true)
      ? make(verb, "read", p, json)
      : null
  }
  if (verb === "list") {
    const p = splitOptions(args.slice(2), READ_OPTIONS)
    return p &&
      p.positionals.length === 1 &&
      READ_TYPES.has(p.positionals[0]) &&
      scopeMatches(p, context, Boolean(context.sandbox))
      ? make(verb, "read", p, json)
      : null
  }
  if (verb === "get" || verb === "history") {
    const p = splitOptions(
      args.slice(2),
      verb === "get" ? new Set(["--view"]) : new Set(),
    )
    return p &&
      p.positionals.length === 1 &&
      RECORD_ID.test(p.positionals[0]) &&
      (!context.sandbox || known(context, p.positionals[0]))
      ? make(verb, "read", p, json)
      : null
  }
  if (!json || !context.sandbox) return null
  if (verb === "db")
    return args.length === 3 && args[2] === "migrate"
      ? simple("write", ["migrate"])
      : null
  if (verb === "add") {
    const p = splitOptions(args.slice(2), ADD_OPTIONS)
    return p &&
      p.positionals.length === 2 &&
      ADD_TYPES.has(p.positionals[0]) &&
      Boolean(p.positionals[1]) &&
      p.values.get("--scope")?.[0] === context.sandbox.scope &&
      p.values.get("--worktree")?.[0] === context.sandbox.worktree &&
      p.values.get("--branch")?.[0] === context.sandbox.branch
      ? make(verb, "write", p, json)
      : null
  }
  if (verb === "set") {
    const p = splitOptions(args.slice(2), REPAIR_OPTIONS)
    return p &&
      p.positionals.length === 3 &&
      /^(?:task|epic)_\d+$/.test(p.positionals[0]) &&
      known(context, p.positionals[0]) &&
      SET_FIELDS.has(p.positionals[1]) &&
      Boolean(p.positionals[2]) &&
      Boolean(p.values.get("--reason")?.[0]?.trim()) &&
      /^[1-9]\d*$/.test(p.values.get("--expected-revision")?.[0] ?? "")
      ? make(verb, "write", p, json)
      : null
  }
  if (verb === "link") {
    const p = splitOptions(args.slice(2), LINK_OPTIONS)
    return p &&
      p.positionals.length === 3 &&
      isPlanningLink(...(p.positionals as [string, string, string])) &&
      known(context, p.positionals[0]) &&
      known(context, p.positionals[2])
      ? make(verb, "write", p, json)
      : null
  }
  if (verb === "unlink") {
    const p = splitOptions(
      args.slice(2),
      new Set(["--reason", "--actor", "--request-id"]),
    )
    return p &&
      p.positionals.length === 1 &&
      /^link_\d+$/.test(p.positionals[0]) &&
      known(context, p.positionals[0]) &&
      Boolean(p.values.get("--reason")?.[0]?.trim())
      ? make(verb, "write", p, json)
      : null
  }
  if (verb === "archive" || verb === "restore") {
    const p = splitOptions(
      args.slice(2),
      new Set(["--reason", "--apply", "--actor", "--request-id"]),
    )
    const hash = p?.values.get("--apply")?.[0]
    return p &&
      p.positionals.length === 1 &&
      /^(?:memory|doc)_\d+$/.test(p.positionals[0]) &&
      known(context, p.positionals[0]) &&
      Boolean(p.values.get("--reason")?.[0]?.trim()) &&
      (!hash || /^[a-f0-9]{64}$/.test(hash))
      ? make(verb, hash ? "write" : "read", p, json)
      : null
  }
  return null
}
export function inspectTaskerCommand(
  command: string,
  context: TaskerCommandContext = {},
): readonly TaskerCommandInspection[] | null {
  const tokens = parseShell(command, context.sessionID)
  if (!tokens) return null
  if (tokens.length === 3 && tokens.join(" ") === "command -v oc")
    return [
      {
        kind: "read",
        verb: "command",
        positionals: [],
        options: {},
        json: false,
      },
    ]
  const normalized = normalize(tokens)
  const result =
    normalized && inspect(normalized.args, normalized.json, context)
  return result ? [result] : null
}
export function isAllowedTaskerCommand(
  command: string,
  context: TaskerCommandContext = {},
): boolean {
  return inspectTaskerCommand(command, context) !== null
}

const RECORD_ID_FIELDS = new Set(["id", "from_id", "to_id"])
const ERROR_FIELDS = new Set(["error", "errors", "stderr"])

function collectStructuredRecordIds(
  value: unknown,
  matches: Set<string>,
): void {
  if (!value || typeof value !== "object") {
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      collectStructuredRecordIds(item, matches)
    }
    return
  }
  const record = value as Record<string, unknown>
  if ([...ERROR_FIELDS].some((field) => record[field])) {
    return
  }
  for (const [key, item] of Object.entries(record)) {
    if (
      RECORD_ID_FIELDS.has(key) &&
      typeof item === "string" &&
      RECORD_ID.test(item)
    ) {
      matches.add(item)
      continue
    }
    if (item && typeof item === "object") {
      collectStructuredRecordIds(item, matches)
    }
  }
}

export function extractTaskerRecordIds(value: unknown): Set<string> {
  const matches = new Set<string>()
  if (typeof value === "string") {
    try {
      collectStructuredRecordIds(JSON.parse(value), matches)
    } catch {
      return matches
    }
  } else {
    collectStructuredRecordIds(value, matches)
  }
  return matches
}
