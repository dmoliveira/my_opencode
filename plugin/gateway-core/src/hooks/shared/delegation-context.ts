const GENERATED_LINE_PATTERNS: Array<{ prefix: string; pattern: RegExp }> = [
  {
    prefix: "[SUBAGENT",
    pattern: /^\[SUBAGENT(?: [^\]]+)?\] .+ \[[^\]]+\] \| effort=(?:low|medium|high)$/,
  },
  {
    prefix: "[DELEGATION ROUTER",
    pattern: /^\[DELEGATION ROUTER(?: [^\]]+)?\] inferred subagent_type=.+ from delegation intent\.$/,
  },
  {
    prefix: "[MODEL ROUTING",
    pattern:
      /^\[MODEL ROUTING(?: [^\]]+)?\] Preferred category=.+; model=.+; reasoning=.+; fallback_policy=.+\.$/,
  },
  {
    prefix: "[TOOL SURFACE",
    pattern: /^\[TOOL SURFACE(?: [^\]]+)?\] subagent=.+; allowed=.*; denied=.*\.$/,
  },
  {
    prefix: "[SESSION FLOW",
    pattern: /^\[SESSION FLOW(?: [^\]]+)?\] parent_session_id=.+; trace_id=.+$/,
  },
  {
    prefix: "[WORKTREE CONTEXT",
    pattern:
      /^\[WORKTREE CONTEXT(?: [^\]]+)?\] cwd=.+; execute file discovery and validation relative to this path unless prompt explicitly overrides\.$/,
  },
  {
    prefix: "[DELEGATION TRACE ",
    pattern: /^\[DELEGATION TRACE [A-Za-z0-9_-]+\]$/,
  },
  {
    prefix: "[HOOK SEMANTIC BRIDGE]",
    pattern:
      /^\[HOOK SEMANTIC BRIDGE\] Upstream semantics detected\. Local runtime mappings: .+\.$/,
  },
  {
    prefix: "[adaptive-delegation-policy]",
    pattern:
      /^\[adaptive-delegation-policy\] cooldown active; recent_failures=\d+\/\d+; prefer low-risk scoped delegation and explicit validation steps\.$/,
  },
  {
    prefix: "[DELEGATION LEARNER]",
    pattern:
      /^\[DELEGATION LEARNER\] Recent outcomes for .+: failures=\d+\/\d+ \(\d+\.\d+\)\. Prefer resilient, scoped delegation with explicit validation and fallback steps\.$/,
  },
  {
    prefix: "[delegation-fallback-orchestrator]",
    pattern:
      /^\[delegation-fallback-orchestrator\] previous delegation failed; applying fallback route category=general and removing explicit subagent_type\.$/,
  },
]

interface ManagedRange {
  start: number
  end: number
}

const TASK_FOCUS_MARKER = "[agent-context-shaper] delegated task focus"
const FOCUS_VALUE_PATTERN = String.raw`[^\r\n\u2028\u2029]+`

function isGeneratedLine(line: string, prefixes: string[]): boolean {
  return GENERATED_LINE_PATTERNS.some(
    ({ prefix, pattern }) => prefixes.includes(prefix) && pattern.test(line),
  )
}

function removeManagedRanges(original: string, ranges: ManagedRange[]): string {
  if (ranges.length === 0) {
    return original
  }
  const ordered = [...ranges].sort((left, right) => left.start - right.start || left.end - right.end)
  const output: string[] = []
  let cursor = 0
  for (const range of ordered) {
    if (range.end <= cursor) {
      continue
    }
    const start = Math.max(cursor, range.start)
    output.push(original.slice(cursor, start))
    cursor = Math.max(cursor, range.end)
  }
  output.push(original.slice(cursor))
  return output.join("")
}

function generatedLineRanges(original: string, prefixes: string[]): ManagedRange[] {
  const ranges: ManagedRange[] = []
  let lineStart = 0
  while (lineStart < original.length) {
    const lfIndex = original.indexOf("\n", lineStart)
    const segmentEnd = lfIndex >= 0 ? lfIndex : original.length
    const hasCrLf = lfIndex >= 0 && segmentEnd > lineStart && original[segmentEnd - 1] === "\r"
    const contentEnd = hasCrLf ? segmentEnd - 1 : segmentEnd
    const line = original.slice(lineStart, contentEnd)
    if (isGeneratedLine(line, prefixes)) {
      let rangeEnd = contentEnd
      if (lfIndex >= 0 && !hasCrLf) {
        rangeEnd = lfIndex + 1
        if (original[rangeEnd] === "\n") {
          rangeEnd += 1
        }
      }
      ranges.push({ start: lineStart, end: rangeEnd })
    }
    if (lfIndex < 0) {
      break
    }
    lineStart = lfIndex + 1
  }
  return ranges
}

function stripGeneratedLines(original: string, prefixes: string[]): string {
  return removeManagedRanges(original, generatedLineRanges(original, prefixes))
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function isGeneratedPromptBlock(paragraph: string, marker: string, block: string): boolean {
  if (paragraph === block) {
    return true
  }
  if (marker !== TASK_FOCUS_MARKER) {
    return false
  }
  const escapedMarker = escapeRegExp(marker)
  const compact = new RegExp(
    `^${escapedMarker}: one objective, then return; prioritize: ${FOCUS_VALUE_PATTERN}; avoid: ${FOCUS_VALUE_PATTERN}; report extras as follow-ups\\.$`,
  )
  const legacy = new RegExp(
    `^${escapedMarker}\n- execute one delegated objective for this task call before returning control\n- prioritize: ${FOCUS_VALUE_PATTERN}\n- avoid: ${FOCUS_VALUE_PATTERN}\n- if you uncover extra work, report it as a follow-up instead of expanding scope in the same delegation$`,
  )
  return compact.test(paragraph) || legacy.test(paragraph)
}

function generatedPromptBlockRanges(original: string, marker: string, block: string): ManagedRange[] {
  const ranges: ManagedRange[] = []
  let paragraphStart = 0
  while (paragraphStart <= original.length) {
    const separatorStart = original.indexOf("\n\n", paragraphStart)
    const paragraphEnd = separatorStart >= 0 ? separatorStart : original.length
    const paragraph = original.slice(paragraphStart, paragraphEnd)
    if (isGeneratedPromptBlock(paragraph, marker, block)) {
      ranges.push({
        start: paragraphStart,
        end: separatorStart >= 0 ? separatorStart + 2 : paragraphEnd,
      })
    }
    if (separatorStart < 0) {
      break
    }
    paragraphStart = separatorStart + 2
  }
  return ranges
}

export function stripDelegationDescriptionContext(original: string): string {
  return stripGeneratedLines(
    original,
    GENERATED_LINE_PATTERNS.map(({ prefix }) => prefix),
  )
}

export function stripDelegationPromptContext(original: string): string {
  return stripGeneratedLines(original, [
    "[SUBAGENT",
    "[DELEGATION ROUTER",
    "[MODEL ROUTING",
    "[TOOL SURFACE",
    "[SESSION FLOW",
    "[WORKTREE CONTEXT",
  ])
}

export function upsertDelegationPromptLine(original: string, prefix: string, line: string): string {
  const cleaned = stripGeneratedLines(original, [prefix])
  return cleaned.length > 0 ? `${line}\n\n${cleaned}` : line
}

export function upsertDelegationPromptBlock(original: string, marker: string, block: string): string {
  const cleaned = removeManagedRanges(original, generatedPromptBlockRanges(original, marker, block))
  return cleaned.length > 0 ? `${block}\n\n${cleaned}` : block
}
