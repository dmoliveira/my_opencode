const ALLOWED_PROTECTED_SHELL_PATTERNS: RegExp[] = [
  /^pwd$/i,
  /^ls(?:\s+[^;&|]+)*$/i,
  /^git\s+status(?:\s+[^;&|]+)*$/i,
  /^git\s+diff(?:\s+[^;&|]+)*$/i,
  /^git\s+log(?:\s+[^;&|]+)*$/i,
  /^git\s+branch\s+--show-current$/i,
  /^git\s+rev-parse(?:\s+[^;&|]+)+$/i,
  /^git\s+worktree\s+list(?:\s+[^;&|]+)*$/i,
  /^git\s+fetch$/i,
  /^git\s+fetch\s+--prune$/i,
  /^git\s+pull\s+--rebase$/i,
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
