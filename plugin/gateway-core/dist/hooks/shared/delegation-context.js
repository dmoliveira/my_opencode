const GENERATED_LINE_PATTERNS = [
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
        pattern: /^\[MODEL ROUTING(?: [^\]]+)?\] Preferred category=.+; model=.+; reasoning=.+; fallback_policy=.+\.$/,
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
        pattern: /^\[WORKTREE CONTEXT(?: [^\]]+)?\] cwd=.+; execute file discovery and validation relative to this path unless prompt explicitly overrides\.$/,
    },
    {
        prefix: "[DELEGATION TRACE ",
        pattern: /^\[DELEGATION TRACE [A-Za-z0-9_-]+\]$/,
    },
    {
        prefix: "[HOOK SEMANTIC BRIDGE]",
        pattern: /^\[HOOK SEMANTIC BRIDGE\] Upstream semantics detected\. Local runtime mappings: .+\.$/,
    },
    {
        prefix: "[adaptive-delegation-policy]",
        pattern: /^\[adaptive-delegation-policy\] cooldown active; recent_failures=\d+\/\d+; prefer low-risk scoped delegation and explicit validation steps\.$/,
    },
    {
        prefix: "[DELEGATION LEARNER]",
        pattern: /^\[DELEGATION LEARNER\] Recent outcomes for .+: failures=\d+\/\d+ \(\d+\.\d+\)\. Prefer resilient, scoped delegation with explicit validation and fallback steps\.$/,
    },
    {
        prefix: "[delegation-fallback-orchestrator]",
        pattern: /^\[delegation-fallback-orchestrator\] previous delegation failed; applying fallback route category=general and removing explicit subagent_type\.$/,
    },
];
function isGeneratedLine(line, prefixes) {
    return GENERATED_LINE_PATTERNS.some(({ prefix, pattern }) => prefixes.includes(prefix) && pattern.test(line));
}
function stripGeneratedLines(original, prefixes) {
    let changed = false;
    const result = original.replace(/[^\r\n]*(?:\r?\n|$)/g, (lineWithEnding) => {
        const line = lineWithEnding.replace(/\r?\n$/, "");
        if (!isGeneratedLine(line, prefixes)) {
            return lineWithEnding;
        }
        changed = true;
        return "";
    });
    if (!changed) {
        return original;
    }
    return result.replace(/^(?:\r?\n)+/, "");
}
export function stripDelegationDescriptionContext(original) {
    return stripGeneratedLines(original, GENERATED_LINE_PATTERNS.map(({ prefix }) => prefix));
}
export function stripDelegationPromptContext(original) {
    return stripGeneratedLines(original, [
        "[SUBAGENT",
        "[DELEGATION ROUTER",
        "[MODEL ROUTING",
        "[TOOL SURFACE",
        "[SESSION FLOW",
        "[WORKTREE CONTEXT",
    ]);
}
export function upsertDelegationPromptLine(original, prefix, line) {
    const cleaned = stripGeneratedLines(original, [prefix]);
    return cleaned.trim() ? `${line}\n\n${cleaned}` : line;
}
export function upsertDelegationPromptBlock(original, marker, block) {
    const paragraphs = original.includes(marker)
        ? original.split(/\r?\n\r?\n/).filter((paragraph) => !paragraph.startsWith(marker))
        : [original];
    const cleaned = paragraphs.join("\n\n").replace(/^(?:\r?\n)+/, "");
    return cleaned.trim() ? `${block}\n\n${cleaned}` : block;
}
