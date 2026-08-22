import type { ValidationEvidenceCategory } from "../validation-evidence-ledger/evidence.js"
import { isAbsolute, resolve } from "node:path"

const LEADING_ENV_ASSIGNMENTS = /^(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S+)\s+)*/
const UV_WRAPPER = "(?:uvx|uv\\s+run)\\s+"
const MAKE_VALIDATE = "make(?:\\s+-C\\s+(?:\"[^\"]*\"|'[^']*'|\\S+))?\\s+validate\\b"
const LINT_COMMAND = new RegExp(
  `^(?:${UV_WRAPPER})?(?:eslint\\b|ruff\\s+check\\b|ruff\\s+format\\s+--check\\b|npm(?:\\s+--prefix\\s+\\S+)?\\s+run\\s+lint\\b|pnpm(?:\\s+(?:--filter\\s+\\S+)*)?\\s+(?:run\\s+)?lint\\b|yarn\\s+(?:run\\s+)?lint\\b|biome\\s+check\\b|golangci-lint\\b|cargo\\s+clippy\\b|${MAKE_VALIDATE})`,
  "i",
)
const TEST_COMMAND = new RegExp(
  `^(?:npm(?:\\s+--prefix\\s+\\S+)?\\s+(?:run\\s+)?test\\b|pnpm(?:\\s+(?:--filter\\s+\\S+)*)?\\s+(?:run\\s+)?test\\b|yarn\\s+(?:run\\s+)?test\\b|bun\\s+test\\b|node\\s+--test\\b|(?:npm|pnpm)\\s+exec\\s+vitest\\b|npx\\s+vitest\\b|python\\d?\\s+-m\\s+pytest\\b|python\\d?\\s+-m\\s+unittest\\b|uv\\s+run\\s+pytest\\b|pytest\\b|vitest\\b|jest\\b|go\\s+test\\b|cargo\\s+test\\b|pre-commit\\s+run\\b|make\\s+selftest\\b|make\\s+install-test\\b|python\\d?\\s+scripts/selftest\\.py\\b|\\./scripts/ci-check\\b.*\\btest[s]?\\b|${MAKE_VALIDATE})`,
  "i",
)
const TYPECHECK_COMMAND = /^(tsc\b|npm(?:\s+--prefix\s+\S+)?\s+run\s+typecheck\b|pnpm(?:\s+(?:--filter\s+\S+)*)?\s+(?:run\s+)?typecheck\b|yarn\s+(?:run\s+)?typecheck\b|pyright\b|mypy\b|cargo\s+check\b|go\s+vet\b)/i
const BUILD_COMMAND = /^(npm(?:\s+--prefix\s+\S+)?\s+run\s+build\b|pnpm(?:\s+(?:--filter\s+\S+)*)?\s+(?:run\s+)?build\b|yarn\s+(?:run\s+)?build\b|vite\s+build\b|next\s+build\b|cargo\s+build\b|go\s+build\b)/i
const SECURITY_COMMAND = /^(npm\s+audit\b|pnpm\s+audit\b|yarn\s+audit\b|cargo\s+audit\b|semgrep\b|codeql\b|snyk\b)/i

function hasShellControlSyntax(command: string): boolean {
  let quote: "'" | '"' | null = null
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index]
    const next = command[index + 1] ?? ""
    if (quote) {
      if (char === quote) {
        quote = null
      } else if (char === "\\" && quote === '"') {
        index += 1
      } else if (char === "`" || (char === "$" && next === "(")) {
        return true
      }
      continue
    }
    if (char === "'" || char === '"') {
      quote = char
      continue
    }
    if (char === "\\") {
      index += 1
      continue
    }
    if ([";", "&", "|", "<", ">", "`", "\n", "\r"].includes(char)) {
      return true
    }
    if (char === "$" && next === "(") {
      return true
    }
  }
  return quote !== null
}

function standaloneCommand(command: string): string {
  const trimmed = command.trim()
  if (!trimmed || hasShellControlSyntax(trimmed)) {
    return ""
  }
  return trimmed.replace(LEADING_ENV_ASSIGNMENTS, "").trim()
}

export function validationCommandDirectory(command: string, fallback: string): string {
  const candidate = standaloneCommand(command)
  const match = candidate.match(/^make\s+-C\s+("[^"]*"|'[^']*'|\S+)\s+validate\b/i)
  if (!match) {
    return fallback
  }
  const configuredDirectory = match[1].replace(/^(?:"|')|(?:"|')$/g, "")
  return isAbsolute(configuredDirectory) ? resolve(configuredDirectory) : fallback
}

export function classifyValidationCommand(command: string): ValidationEvidenceCategory[] {
  const candidate = standaloneCommand(command)
  if (!candidate || /^cd(?:\s|$)/i.test(candidate)) {
    return []
  }
  const categories = new Set<ValidationEvidenceCategory>()
  if (LINT_COMMAND.test(candidate)) {
    categories.add("lint")
  }
  if (TEST_COMMAND.test(candidate)) {
    categories.add("test")
  }
  if (TYPECHECK_COMMAND.test(candidate)) {
    categories.add("typecheck")
  }
  if (BUILD_COMMAND.test(candidate)) {
    categories.add("build")
  }
  if (SECURITY_COMMAND.test(candidate)) {
    categories.add("security")
  }
  return [...categories]
}

export function isValidationCommand(command: string): boolean {
  return classifyValidationCommand(command).length > 0
}
