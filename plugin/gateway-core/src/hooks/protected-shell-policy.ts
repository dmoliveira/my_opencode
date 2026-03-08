const GIT_SAFE_GLOBAL_FLAGS = String.raw`(?:\s+--no-pager)?`
const GIT_SAFE_ARGS = String.raw`(?:\s+[^;&|]+)*`
const GIT_REQUIRED_ARGS = String.raw`(?:\s+[^;&|]+)+`

function gitProtectedPattern(subcommandPattern: string, argsPattern = GIT_SAFE_ARGS): RegExp {
  return new RegExp(String.raw`^git${GIT_SAFE_GLOBAL_FLAGS}\s+${subcommandPattern}${argsPattern}$`, "i")
}

const ALLOWED_PROTECTED_SHELL_PATTERNS: RegExp[] = [
  /^pwd$/i,
  /^ls(?:\s+[^;&|]+)*$/i,
  gitProtectedPattern("status"),
  gitProtectedPattern("diff"),
  gitProtectedPattern("log"),
  gitProtectedPattern(String.raw`branch\s+--show-current`, ""),
  gitProtectedPattern("rev-parse", GIT_REQUIRED_ARGS),
  gitProtectedPattern(String.raw`worktree\s+list`),
  gitProtectedPattern("fetch", ""),
  gitProtectedPattern(String.raw`fetch\s+--prune`, ""),
  gitProtectedPattern(String.raw`pull\s+--rebase`, ""),
  /^gh\s+pr\s+view(?:\s+[^;&|]+)*$/i,
  /^gh\s+pr\s+checks(?:\s+[^;&|]+)*$/i,
  /^make\s+(?:help|validate|selftest|doctor|doctor-json|install-test|release-check)$/i,
  /^npm(?:\s+--prefix\s+[^;&|]+)?\s+(?:test|run\s+(?:lint|test|build))$/i,
  /^pnpm(?:\s+--dir\s+[^;&|]+)?\s+(?:test|lint|build)$/i,
  /^yarn(?:\s+--cwd\s+[^;&|]+)?\s+(?:test|lint|build)$/i,
  /^bun(?:\s+--cwd\s+[^;&|]+)?\s+(?:test|run\s+(?:lint|test|build))$/i,
  /^python3?\s+-m\s+(?:unittest|pytest|py_compile)(?:\s+[^;&|]+)*$/i,
  /^pytest(?:\s+[^;&|]+)*$/i,
  /^node\s+--test(?:\s+[^;&|]+)*$/i,
  /^pre-commit\s+run(?:\s+[^;&|]+)*$/i,
  /^eslint(?:\s+[^;&|]+)*$/i,
  /^tsc(?:\s+[^;&|]+)*$/i,
  /^ruff(?:\s+[^;&|]+)*$/i,
]

export function normalizeShellCommand(command: string): string {
  return command.replace(/\s+/g, " ").trim()
}

export function hasDisallowedShellSyntax(command: string): boolean {
  return /&&|\|\||;|\n|\||[<>`]|\$\(|\(|\)/.test(command)
}

export function isAllowedProtectedShellCommand(command: string): boolean {
  if (hasDisallowedShellSyntax(command)) {
    return false
  }
  const normalized = normalizeShellCommand(command)
  return ALLOWED_PROTECTED_SHELL_PATTERNS.some((pattern) => pattern.test(normalized))
}
