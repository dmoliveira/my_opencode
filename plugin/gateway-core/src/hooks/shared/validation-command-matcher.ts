import type { ValidationEvidenceCategory } from "../validation-evidence-ledger/evidence.js"

const LEADING_ENV_ASSIGNMENTS = /^(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*/
const UV_WRAPPER = "(?:uvx|uv\\s+run)\\s+"
const LINT_COMMAND = new RegExp(
  `^(?:${UV_WRAPPER})?(?:eslint\\b|ruff\\s+check\\b|ruff\\s+format\\s+--check\\b|npm(?:\\s+--prefix\\s+\\S+)?\\s+run\\s+lint\\b|pnpm(?:\\s+(?:--filter\\s+\\S+)*)?\\s+(?:run\\s+)?lint\\b|yarn\\s+(?:run\\s+)?lint\\b|biome\\s+check\\b|golangci-lint\\b|cargo\\s+clippy\\b|make\\s+validate\\b)`,
  "i",
)
const TEST_COMMAND = /^(npm(?:\s+--prefix\s+\S+)?\s+(run\s+)?test\b|pnpm(?:\s+(?:--filter\s+\S+)*)?\s+(?:run\s+)?test\b|yarn\s+(?:run\s+)?test\b|bun\s+test\b|node\s+--test\b|(?:npm|pnpm)\s+exec\s+vitest\b|npx\s+vitest\b|python\d?\s+-m\s+pytest\b|python\d?\s+-m\s+unittest\b|uv\s+run\s+pytest\b|pytest\b|vitest\b|jest\b|go\s+test\b|cargo\s+test\b|pre-commit\s+run\b|make\s+selftest\b|make\s+install-test\b|python\d?\s+scripts\/selftest\.py\b|\.\/scripts\/ci-check\b.*\btest[s]?\b)/i
const TYPECHECK_COMMAND = /^(tsc\b|npm(?:\s+--prefix\s+\S+)?\s+run\s+typecheck\b|pnpm(?:\s+(?:--filter\s+\S+)*)?\s+(?:run\s+)?typecheck\b|yarn\s+(?:run\s+)?typecheck\b|pyright\b|mypy\b|cargo\s+check\b|go\s+vet\b)/i
const BUILD_COMMAND = /^(npm(?:\s+--prefix\s+\S+)?\s+run\s+build\b|pnpm(?:\s+(?:--filter\s+\S+)*)?\s+(?:run\s+)?build\b|yarn\s+(?:run\s+)?build\b|vite\s+build\b|next\s+build\b|cargo\s+build\b|go\s+build\b)/i
const SECURITY_COMMAND = /^(npm\s+audit\b|pnpm\s+audit\b|yarn\s+audit\b|cargo\s+audit\b|semgrep\b|codeql\b|snyk\b)/i

function commandSegments(command: string): string[] {
  return command
    .split(/&&|\|\||;/)
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment) => segment.replace(LEADING_ENV_ASSIGNMENTS, "").trim())
    .filter(Boolean)
}

export function classifyValidationCommand(command: string): ValidationEvidenceCategory[] {
  const segments = commandSegments(command)
  if (segments.length === 0) {
    return []
  }
  const categories = new Set<ValidationEvidenceCategory>()
  for (const segment of segments) {
    if (LINT_COMMAND.test(segment)) {
      categories.add("lint")
    }
    if (TEST_COMMAND.test(segment)) {
      categories.add("test")
    }
    if (TYPECHECK_COMMAND.test(segment)) {
      categories.add("typecheck")
    }
    if (BUILD_COMMAND.test(segment)) {
      categories.add("build")
    }
    if (SECURITY_COMMAND.test(segment)) {
      categories.add("security")
    }
  }
  return [...categories]
}

export function isValidationCommand(command: string): boolean {
  return classifyValidationCommand(command).length > 0
}
