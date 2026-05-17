const SHELL_TOKEN = String.raw`(?:"[^"]*"|'[^']*'|[^\s;&|]+)`
const GIT_SAFE_GLOBAL_FLAGS = String.raw`(?:\s+(?:--no-pager|-C\s+${SHELL_TOKEN}|--git-dir\s+${SHELL_TOKEN}|--work-tree\s+${SHELL_TOKEN}))*`
const GIT_SAFE_ARGS = String.raw`(?:\s+[^;&|]+)*`
const GIT_SINGLE_ARG = String.raw`(?:\s+${SHELL_TOKEN})`
const GIT_REQUIRED_ARGS = String.raw`(?:\s+[^;&|]+)+`
const SAFE_ENV_KEY = String.raw`(?:CI|GIT_TERMINAL_PROMPT|GIT_EDITOR|GIT_PAGER|PAGER|GCM_INTERACTIVE|OPENCODE_SESSION_ID)`
const SAFE_ENV_PREFIX = String.raw`(?:(?:env\s+)?(?:${SAFE_ENV_KEY}=${SHELL_TOKEN}\s+)*)`
const OPTIONAL_RTK_WRAPPER = String.raw`(?:(?:[^\s;&|]*/)?rtk\s+)?`
const PROTECTED_BRANCH_REF = String.raw`(?:main|master)`
const SQLITE_SAFE_FLAG = String.raw`(?:-readonly|-header|-column|-csv|-json|-line|-list)`
const GH_PROTECTED_BINARY = String.raw`${OPTIONAL_RTK_WRAPPER}(?:[^\s;&|]*/)?gh`
const OC_PROTECTED_BINARY = String.raw`(?:[^\s;&|]*/)?oc`
const TRUE_PATTERN = new RegExp(String.raw`^${SAFE_ENV_PREFIX}true$`, "i")
const PRINTF_LITERAL_PATTERN = new RegExp(
  String.raw`^${SAFE_ENV_PREFIX}printf\s+(?:'[^']*'|"[^"]*")(?:\s+(?:'[^']*'|"[^"]*"))*$`,
  "i",
)
const OC_STATUS_PATTERN = new RegExp(
  String.raw`^${SAFE_ENV_PREFIX}${OC_PROTECTED_BINARY}\s+(?:current|next|queue)(?:\s+.+)?$`,
  "i",
)
const SQLITE_DANGEROUS_TOKEN_PATTERN =
  /\b(?:load_extension|readfile|writefile|attach|vacuum|alter|insert|update|delete|replace|create|drop|reindex|analyze|backup|restore|detach)\b/i

function protectedPattern(commandPattern: string): RegExp {
  return new RegExp(String.raw`^${SAFE_ENV_PREFIX}${commandPattern}$`, "i")
}

function gitProtectedPattern(subcommandPattern: string, argsPattern = GIT_SAFE_ARGS): RegExp {
  return protectedPattern(
    String.raw`${OPTIONAL_RTK_WRAPPER}(?:[^\s;&|]*/)?git${GIT_SAFE_GLOBAL_FLAGS}\s+${subcommandPattern}${argsPattern}`,
  )
}

function ocProtectedPattern(subcommandPattern: string, argsPattern = GIT_SAFE_ARGS): RegExp {
  return protectedPattern(String.raw`${OC_PROTECTED_BINARY}\s+${subcommandPattern}${argsPattern}`)
}

const READ_ONLY_GIT_PATTERNS: RegExp[] = [
  gitProtectedPattern("status"),
  gitProtectedPattern("diff"),
  gitProtectedPattern("log"),
  gitProtectedPattern(String.raw`remote\s+-v`, ""),
  gitProtectedPattern(String.raw`branch\s+--show-current`, ""),
  gitProtectedPattern(String.raw`branch\s+-r(?:\s+--contains\s+[^;&|]+)?`, ""),
  gitProtectedPattern(String.raw`branch\s+(?:--list|-a)`, GIT_SAFE_ARGS),
  gitProtectedPattern(String.raw`remote\s+get-url`, GIT_SINGLE_ARG),
  gitProtectedPattern(String.raw`remote\s+add`, `${GIT_SINGLE_ARG}${GIT_SINGLE_ARG}`),
  gitProtectedPattern(String.raw`remote\s+set-url`, `${GIT_SINGLE_ARG}${GIT_SINGLE_ARG}`),
  gitProtectedPattern("rev-parse", GIT_REQUIRED_ARGS),
  gitProtectedPattern("rev-list", GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`merge-base`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`show`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`ls-files`, GIT_SAFE_ARGS),
  gitProtectedPattern(String.raw`for-each-ref`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`symbolic-ref`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`worktree\s+list`, GIT_SAFE_ARGS),
]

const SAFE_GIT_CLEANUP_PATTERNS: RegExp[] = [
  gitProtectedPattern(String.raw`branch\s+(?:-d|--delete)`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`worktree\s+add`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`worktree\s+remove`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`switch\s+--detach\s+(?:origin/)?${PROTECTED_BRANCH_REF}`, ""),
  gitProtectedPattern(String.raw`checkout\s+--detach\s+(?:origin/)?${PROTECTED_BRANCH_REF}`, ""),
]

const ALLOWED_PROTECTED_SHELL_PATTERNS: RegExp[] = [
  protectedPattern(String.raw`date(?:\s+[^;&|]+)*`),
  protectedPattern("pwd"),
  protectedPattern(String.raw`ls(?:\s+[^;&|]+)*`),
  ...READ_ONLY_GIT_PATTERNS,
  ...SAFE_GIT_CLEANUP_PATTERNS,
  gitProtectedPattern("fetch", ""),
  gitProtectedPattern(String.raw`fetch(?:\s+--(?:all|prune|quiet))*(?:\s+(?!-)${SHELL_TOKEN})?`, ""),
  gitProtectedPattern(String.raw`fetch\s+--prune`, ""),
  gitProtectedPattern(String.raw`pull\s+--rebase`, ""),
  gitProtectedPattern(String.raw`pull\s+--rebase\s+--autostash`, ""),
  gitProtectedPattern(String.raw`pull\s+--rebase(?:\s+--autostash)?\s+origin\s+${PROTECTED_BRANCH_REF}`, ""),
  gitProtectedPattern(String.raw`merge\s+--(?:no-edit|ff-only)`, GIT_SINGLE_ARG),
  gitProtectedPattern(String.raw`push(?:\s+(?:-u|--set-upstream))?\s+origin\s+${PROTECTED_BRANCH_REF}`, ""),
  gitProtectedPattern(String.raw`stash\s+push`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`stash\s+list`),
  gitProtectedPattern(String.raw`stash\s+show`),
  gitProtectedPattern(String.raw`restore\s+--source\s+${PROTECTED_BRANCH_REF}\s+--`, GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`checkout\s+${PROTECTED_BRANCH_REF}\s+--`, GIT_REQUIRED_ARGS),
  ocProtectedPattern(String.raw`(?:current|next|queue)`, GIT_SAFE_ARGS),
  ocProtectedPattern(String.raw`resume`, GIT_REQUIRED_ARGS),
  ocProtectedPattern(String.raw`done`, GIT_REQUIRED_ARGS),
  ocProtectedPattern(String.raw`end-session`, GIT_REQUIRED_ARGS),
  protectedPattern(String.raw`${GH_PROTECTED_BINARY}\s+auth\s+status(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`${GH_PROTECTED_BINARY}\s+pr\s+view(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`${GH_PROTECTED_BINARY}\s+pr\s+checks(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`${GH_PROTECTED_BINARY}\s+repo\s+view(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`${GH_PROTECTED_BINARY}\s+repo\s+create(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`${GH_PROTECTED_BINARY}\s+repo\s+edit(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`${GH_PROTECTED_BINARY}\s+api\s+user(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`make\s+(?:help|validate|selftest|doctor|doctor-json|install-test|release-check)`),
  protectedPattern(String.raw`npm\s+install\s+--yes(?:\s+--(?:no-audit|no-fund|silent|ignore-scripts))*`),
  protectedPattern(String.raw`npm\s+ci\s+--yes(?:\s+--(?:no-audit|no-fund|silent|ignore-scripts))*`),
  protectedPattern(String.raw`npm\s+init\s+-y`),
  protectedPattern(String.raw`npm(?:\s+--prefix\s+[^;&|]+)?\s+(?:test|run\s+(?:lint|test|build))`),
  protectedPattern(String.raw`pnpm(?:\s+--dir\s+[^;&|]+)?\s+(?:test|lint|build)`),
  protectedPattern(String.raw`yarn(?:\s+--cwd\s+[^;&|]+)?\s+(?:test|lint|build)`),
  protectedPattern(String.raw`bun(?:\s+--cwd\s+[^;&|]+)?\s+(?:test|run\s+(?:lint|test|build))`),
  protectedPattern(String.raw`python3?\s+-m\s+(?:unittest|pytest|py_compile)(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`pytest(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`node\s+--test(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`pre-commit\s+run(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`eslint(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`tsc(?:\s+[^;&|]+)*`),
  protectedPattern(String.raw`ruff(?:\s+[^;&|]+)*`),
]

export function isReadOnlyGitCommand(command: string): boolean {
  return READ_ONLY_GIT_PATTERNS.some((pattern) => pattern.test(normalizeShellCommand(command)))
}

export function isSafeGitCleanupCommand(command: string): boolean {
  return SAFE_GIT_CLEANUP_PATTERNS.some((pattern) => pattern.test(normalizeShellCommand(command)))
}

export function normalizeShellCommand(command: string): string {
  return command.replace(/\s+/g, " ").trim()
}

function forEachUnquotedCharacter(command: string, visitor: (char: string, index: number, value: string) => boolean | void): boolean {
  let quote: '"' | "'" | null = null

  for (let index = 0; index < command.length; index += 1) {
    const char = command[index] ?? ""
    if (quote) {
      if (char === quote) {
        quote = null
      } else if (char === "\\" && quote === '"' && index + 1 < command.length) {
        index += 1
      }
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      continue
    }
    if (visitor(char, index, command) === true) {
      return true
    }
  }
  return false
}

export function hasDisallowedShellSyntax(command: string): boolean {
  return forEachUnquotedCharacter(command, (char, index, value) => {
    if (char === "&" && value[index + 1] === "&") {
      return true
    }
    if (char === "|" && value[index + 1] === "|") {
      return true
    }
    if (char === ";" || char === "\n" || char === "|" || char === "<" || char === ">" || char === "`" || char === "(" || char === ")") {
      return true
    }
    if (char === "$" && value[index + 1] === "(") {
      return true
    }
    return false
  })
}

function hasHardDisallowedShellSyntax(command: string): boolean {
  return forEachUnquotedCharacter(command, (char, index, value) => {
    if (char === "|" && value[index + 1] === "|") {
      return true
    }
    if (char === "|" || char === "\n" || char === "<" || char === ">" || char === "`" || char === "(" || char === ")") {
      return true
    }
    if (char === "$" && value[index + 1] === "(") {
      return true
    }
    return false
  })
}

function hasShellExpansionSyntax(command: string): boolean {
  return /`|\$\(|\$\{|\$[A-Za-z_]/.test(command)
}

function splitChainedCommands(command: string): string[] {
  const segments: string[] = []
  let current = ""
  let quote: '"' | "'" | null = null

  for (let index = 0; index < command.length; index += 1) {
    const char = command[index] ?? ""
    if (quote) {
      current += char
      if (char === quote) {
        quote = null
      } else if (char === "\\" && quote === '"' && index + 1 < command.length) {
        current += command[index + 1] ?? ""
        index += 1
      }
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      current += char
      continue
    }
    if (char === ";") {
      const normalized = normalizeShellCommand(current)
      if (normalized) {
        segments.push(normalized)
      }
      current = ""
      continue
    }
    if (char === "&" && command[index + 1] === "&") {
      const normalized = normalizeShellCommand(current)
      if (normalized) {
        segments.push(normalized)
      }
      current = ""
      index += 1
      continue
    }
    current += char
  }

  const normalized = normalizeShellCommand(current)
  if (normalized) {
    segments.push(normalized)
  }
  return segments
}

export function isAllowedProtectedShellCommand(command: string): boolean {
  const normalized = normalizeShellCommand(command)
  if (isAllowedOcStatusBundleCommand(normalized) || isAllowedReadonlySqliteCommand(command)) {
    return true
  }
  if (hasHardDisallowedShellSyntax(command) || hasShellExpansionSyntax(command)) {
    return false
  }
  const commands = splitChainedCommands(normalized)
  if (commands.length === 0) {
    return false
  }
  return commands.every((candidate) => ALLOWED_PROTECTED_SHELL_PATTERNS.some((pattern) => pattern.test(candidate)))
}

function isAllowedOcStatusBundleCommand(command: string): boolean {
  if (!command || hasShellExpansionSyntax(command)) {
    return false
  }
  const segments = splitShellSequence(command)
  if (segments.length === 0) {
    return false
  }
  let sawOcStatus = false
  for (let index = 0; index < segments.length; index += 1) {
    const current = segments[index]
    if (hasDisallowedShellSyntax(current.segment) || hasShellExpansionSyntax(current.segment)) {
      return false
    }
    if (OC_STATUS_PATTERN.test(current.segment)) {
      sawOcStatus = true
    } else if (TRUE_PATTERN.test(current.segment)) {
      if (index === 0 || current.separatorBefore !== "||") {
        return false
      }
    } else if (PRINTF_LITERAL_PATTERN.test(current.segment)) {
      if (index === 0) {
        return false
      }
    } else {
      return false
    }
    if (current.separatorBefore === "||" && !TRUE_PATTERN.test(current.segment)) {
      return false
    }
  }
  return sawOcStatus
}

function isAllowedReadonlySqliteCommand(command: string): boolean {
  if (!command || hasDisallowedShellSyntax(command) || hasShellExpansionSyntax(command)) {
    return false
  }
  const argv = splitShellArgv(command)
  if (argv.length < 3) {
    return false
  }
  const stripped = stripAllowedEnvPrefix(argv)
  if (stripped.length < 3) {
    return false
  }
  if (!/sqlite3$/i.test(stripped[0] ?? "")) {
    return false
  }
  if (!stripped.slice(1).includes("-readonly")) {
    return false
  }
  let offset = 1
  while (offset < stripped.length && new RegExp(`^${SQLITE_SAFE_FLAG}$`, "i").test(stripped[offset] ?? "")) {
    offset += 1
  }
  const trailing = stripped.slice(offset)
  if (trailing.slice(0, -2).some((token) => token.startsWith("-"))) {
    return false
  }
  if (trailing.length < 2) {
    return false
  }
  const statement = String(trailing[trailing.length - 1] ?? "").trim()
  if (!statement) {
    return false
  }
  if (/[\r\n]/.test(statement)) {
    return false
  }
  const normalized = statement.replace(/;\s*$/, "").trim().toLowerCase()
  if (!normalized) {
    return false
  }
  if (normalized === ".tables") {
    return true
  }
  if (normalized.startsWith(".schema")) {
    return true
  }
  if (/^pragma\s+table_info\s*\([^);=]+\)$/i.test(normalized)) {
    return true
  }
  if (SQLITE_DANGEROUS_TOKEN_PATTERN.test(normalized)) {
    return false
  }
  if (normalized.startsWith("select")) {
    return true
  }
  if (normalized.startsWith("with") && /\bselect\b/i.test(normalized)) {
    return true
  }
  return false
}

function splitShellArgv(command: string): string[] {
  const argv: string[] = []
  let current = ""
  let quote: '"' | "'" | null = null
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index] ?? ""
    if (quote) {
      if (char === quote) {
        quote = null
        continue
      }
      if (char === "\\" && quote === '"' && index + 1 < command.length) {
        current += command[index + 1] ?? ""
        index += 1
        continue
      }
      current += char
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      continue
    }
    if (/\s/.test(char)) {
      if (current) {
        argv.push(current)
        current = ""
      }
      continue
    }
    current += char
  }
  if (quote) {
    return []
  }
  if (current) {
    argv.push(current)
  }
  return argv
}

function stripAllowedEnvPrefix(argv: string[]): string[] {
  const remaining = [...argv]
  let explicitEnv = false
  while (remaining.length > 0) {
    const token = remaining[0] ?? ""
    if (/^[A-Za-z_][A-Za-z0-9_]*=.*/.test(token)) {
      const key = token.split("=", 1)[0] ?? ""
      if (!new RegExp(`^${SAFE_ENV_KEY}$`, "i").test(key)) {
        return []
      }
      remaining.shift()
      continue
    }
    if (token === "env") {
      explicitEnv = true
      remaining.shift()
      continue
    }
    if (!explicitEnv) {
      break
    }
    if (token === "--") {
      remaining.shift()
      break
    }
    if (token === "-u" || token === "--unset") {
      remaining.shift()
      const unsetKey = remaining.shift() ?? ""
      if (!new RegExp(`^${SAFE_ENV_KEY}$`, "i").test(unsetKey)) {
        return []
      }
      continue
    }
    if (token.startsWith("--unset=")) {
      const unsetKey = token.slice("--unset=".length)
      if (!new RegExp(`^${SAFE_ENV_KEY}$`, "i").test(unsetKey)) {
        return []
      }
      remaining.shift()
      continue
    }
    if (token.startsWith("-")) {
      return []
    }
    break
  }
  return remaining
}

function splitShellSequence(command: string): Array<{ separatorBefore: string | null; segment: string }> {
  const segments: Array<{ separatorBefore: string | null; segment: string }> = []
  let current = ""
  let quote: '"' | "'" | null = null
  let separatorBefore: string | null = null
  const pushCurrent = (): void => {
    const normalized = normalizeShellCommand(current)
    if (normalized) {
      segments.push({ separatorBefore, segment: normalized })
      separatorBefore = null
    }
    current = ""
  }
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index] ?? ""
    const next = command[index + 1] ?? ""
    if (quote) {
      current += char
      if (char === quote) {
        quote = null
      } else if (char === "\\" && quote === '"' && index + 1 < command.length) {
        current += command[index + 1] ?? ""
        index += 1
      }
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      current += char
      continue
    }
    if (char === ";") {
      pushCurrent()
      separatorBefore = ";"
      continue
    }
    if (char === "&" && next === "&") {
      pushCurrent()
      separatorBefore = "&&"
      index += 1
      continue
    }
    if (char === "|" && next === "|") {
      pushCurrent()
      separatorBefore = "||"
      index += 1
      continue
    }
    current += char
  }
  pushCurrent()
  return segments
}
