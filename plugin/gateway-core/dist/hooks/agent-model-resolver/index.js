import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata } from "../shared/agent-metadata.js";
import { resolveDelegationTraceId } from "../shared/delegation-trace.js";
const MODEL_BY_CATEGORY = {
    quick: { model: "openai/gpt-5.1-codex-mini", reasoning: "low" },
    balanced: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
    deep: { model: "openai/gpt-5.3-codex", reasoning: "high" },
    critical: { model: "openai/gpt-5.3-codex", reasoning: "xhigh" },
    visual: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
    writing: { model: "openai/gpt-5.3-codex", reasoning: "medium" },
};
const ROUTING_PATTERNS = [
    {
        subagentType: "explore",
        patterns: [
            /\b(where|locat(e|ion)|find|search|inventory|map pattern|usage(s)?)\b/i,
            /\bcodebase|repository|module(s)?\b/i,
        ],
    },
    {
        subagentType: "librarian",
        patterns: [
            /\bofficial docs?|upstream|library|framework|api reference\b/i,
            /\bexternal|oss|open\s*source|github\b/i,
        ],
    },
    {
        subagentType: "verifier",
        patterns: [
            /\b(run|execute)\s+(tests?|lint|build)\b/i,
            /\bverify|validation|triage|failing checks?\b/i,
        ],
    },
    {
        subagentType: "reviewer",
        patterns: [
            /\breview|risk|regression|safety|correctness\b/i,
            /\bquality pass|final pass\b/i,
        ],
    },
    {
        subagentType: "release-scribe",
        patterns: [
            /\brelease notes?|changelog|pr summary|release summary\b/i,
            /\bmilestone|announcement\b/i,
        ],
    },
    {
        subagentType: "oracle",
        patterns: [
            /\barchitecture|trade\s*off|security|performance\b/i,
            /\bdebug|hard problem|uncertainty|repeated failures?\b/i,
        ],
    },
    {
        subagentType: "strategic-planner",
        patterns: [
            /\bplan|milestone|roadmap|sequence|execution plan\b/i,
            /\bbreak down|phase(s)?\b/i,
        ],
    },
    {
        subagentType: "ambiguity-analyst",
        patterns: [/\bambiguity|unknowns?|assumption(s)?|decision fork\b/i],
    },
    {
        subagentType: "plan-critic",
        patterns: [/\bcritique|feasibility|coverage|testability|plan review\b/i],
    },
];
const SUBAGENT_ICON_BY_TYPE = {
    explore: { nerd: "󰍉", fallback: "[scan]" },
    librarian: { nerd: "󰂺", fallback: "[docs]" },
    verifier: { nerd: "󰄬", fallback: "[check]" },
    reviewer: { nerd: "󰦨", fallback: "[review]" },
    "release-scribe": { nerd: "󰜘", fallback: "[notes]" },
    oracle: { nerd: "󱠓", fallback: "[advisor]" },
    "strategic-planner": { nerd: "󱎸", fallback: "[plan]" },
    "ambiguity-analyst": { nerd: "󰋗", fallback: "[clarify]" },
    "plan-critic": { nerd: "󰒠", fallback: "[critic]" },
    orchestrator: { nerd: "󰯲", fallback: "[lead]" },
};
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim();
}
function prependHint(original, hint) {
    if (!original.trim()) {
        return hint;
    }
    if (original.includes(hint)) {
        return original;
    }
    return `${hint}\n\n${original}`;
}
function formatTimestamp(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    const seconds = String(date.getSeconds()).padStart(2, "0");
    const time = `${hours}:${minutes}:${seconds}`;
    return {
        full: `${year}-${month}-${day} ${time}`,
        time,
    };
}
function escapeRegex(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function stripHeaderLine(original, header) {
    return original.replace(new RegExp(`^\\[${escapeRegex(header)}(?: [^\\]]+)?\\].*(?:\\n|$)`, "gmi"), "");
}
function stripInjectedHeaders(original) {
    return [
        "SUBAGENT",
        "DELEGATION ROUTER",
        "MODEL ROUTING",
        "TOOL SURFACE",
        "SESSION FLOW",
        "THINKING EFFORT",
    ]
        .reduce((text, header) => stripHeaderLine(text, header), original)
        .trimStart();
}
function formatHeader(header, body, timestamp) {
    const marker = timestamp ? `${header} ${timestamp}` : header;
    return `[${marker}] ${body}`;
}
function inferSubagentType(text, available) {
    const source = text.trim();
    if (!source) {
        return null;
    }
    const lower = source.toLowerCase();
    for (const candidate of available) {
        if (lower.includes(candidate)) {
            return { name: candidate, score: 3 };
        }
    }
    let best = null;
    for (const rule of ROUTING_PATTERNS) {
        if (!available.has(rule.subagentType)) {
            continue;
        }
        const score = rule.patterns.reduce((count, pattern) => (pattern.test(source) ? count + 1 : count), 0);
        if (score <= 0) {
            continue;
        }
        if (!best || score > best.score) {
            best = { name: rule.subagentType, score };
        }
    }
    return best && best.score >= 1 ? best : null;
}
function scoreSubagentIntent(text, subagentType) {
    const source = text.trim();
    if (!source) {
        return 0;
    }
    const lower = source.toLowerCase();
    let score = lower.includes(subagentType) ? 2 : 0;
    const rule = ROUTING_PATTERNS.find((candidate) => candidate.subagentType === subagentType);
    if (!rule) {
        return score;
    }
    score += rule.patterns.reduce((count, pattern) => (pattern.test(source) ? count + 1 : count), 0);
    return score;
}
function normalizeToolList(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter((item) => typeof item === "string")
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
}
const MUTATION_TOOL_MARKERS = new Set(["bash", "write", "edit", "task"]);
const MUTATING_DELEGATION_INTENT_PATTERN = /\bgit\s+commit\b|\bcommit\s+(changes?|code|files?)\b|\b(create|open|file|submit|merge|close|update)\s+(a\s+)?(pr|pull\s*request)\b|\bgh\s+pr\s+(create|merge)\b|\bgit\s+push\b|\bpush\s+(to\s+)?(origin|remote)\b|\bgit\s+(rebase|cherry-pick|reset|amend)\b|\b(edit|modify|rewrite|refactor|implement|apply\s+patch|write)\s+(the\s+)?(code|file|files|docs?|documentation)\b/i;
function enforcesReadOnlySurface(deniedTools) {
    return deniedTools.some((tool) => MUTATION_TOOL_MARKERS.has(String(tool).toLowerCase().trim()));
}
function policyForAgent(subagentType, defaults, overrides) {
    const normalized = subagentType.trim().toLowerCase();
    const policy = overrides[normalized] ?? {};
    const overrideDelta = Math.max(0, Number(policy.overrideDelta ?? defaults.overrideDelta));
    const intentThreshold = Math.max(0, Number(policy.intentThreshold ?? defaults.intentThreshold));
    return { overrideDelta, intentThreshold };
}
function formatSubagentLabel(subagentType, reasoning, timestamp) {
    const icon = SUBAGENT_ICON_BY_TYPE[subagentType] ?? {
        nerd: "󰚩",
        fallback: "[agent]",
    };
    return formatHeader("SUBAGENT", `${icon.nerd} ${subagentType} ${icon.fallback} | effort=${reasoning}`, timestamp);
}
export function createAgentModelResolverHook(options) {
    return {
        id: "agent-model-resolver",
        priority: 289,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase().trim();
            if (tool !== "task") {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const args = eventPayload.output?.args;
            if (!args || typeof args !== "object") {
                return;
            }
            const traceId = resolveDelegationTraceId(args);
            const sid = sessionId(eventPayload);
            const metadataByAgent = loadAgentMetadata(directory);
            const knownAgents = new Set(metadataByAgent.keys());
            const combinedText = `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`;
            let subagentType = String(args.subagent_type ?? "").toLowerCase().trim();
            let routeSource = "explicit_subagent_type";
            if (!subagentType) {
                const inferred = inferSubagentType(combinedText, knownAgents);
                if (inferred) {
                    subagentType = inferred.name;
                    args.subagent_type = inferred.name;
                    routeSource = "inferred_subagent_type";
                }
            }
            else if (knownAgents.has(subagentType)) {
                const policy = policyForAgent(subagentType, {
                    overrideDelta: options.defaultOverrideDelta,
                    intentThreshold: options.defaultIntentThreshold,
                }, options.agentPolicyOverrides);
                const inferred = inferSubagentType(combinedText, knownAgents);
                const explicitScore = scoreSubagentIntent(combinedText, subagentType);
                if (inferred &&
                    inferred.name !== subagentType &&
                    inferred.score >= explicitScore + policy.overrideDelta &&
                    explicitScore < policy.intentThreshold) {
                    const previous = subagentType;
                    subagentType = inferred.name;
                    args.subagent_type = inferred.name;
                    routeSource = "overridden_low_confidence";
                    writeGatewayEventAudit(directory, {
                        hook: "agent-model-resolver",
                        stage: "guard",
                        reason_code: "delegation_route_overridden_low_confidence",
                        session_id: sessionId(eventPayload),
                        trace_id: traceId,
                        original_subagent_type: previous,
                        inferred_subagent_type: inferred.name,
                        original_score: String(explicitScore),
                        inferred_score: String(inferred.score),
                        override_delta: String(policy.overrideDelta),
                        intent_threshold: String(policy.intentThreshold),
                    });
                }
            }
            if (!subagentType || !knownAgents.has(subagentType)) {
                return;
            }
            const metadata = metadataByAgent.get(subagentType);
            const deniedTools = normalizeToolList(metadata?.denied_tools);
            if (MUTATING_DELEGATION_INTENT_PATTERN.test(combinedText) && enforcesReadOnlySurface(deniedTools)) {
                writeGatewayEventAudit(directory, {
                    hook: "agent-model-resolver",
                    stage: "guard",
                    reason_code: "delegation_mutation_intent_blocked",
                    session_id: sid,
                    trace_id: traceId,
                    subagent_type: subagentType,
                    route_source: routeSource,
                });
                throw new Error(`Blocked task delegation for ${subagentType}: prompt requests mutating work but this subagent is read-only. Run commit/PR/edit actions directly with the primary agent.`);
            }
            const explicitCategory = String(args.category ?? "").toLowerCase().trim();
            const requestedCategory = explicitCategory && MODEL_BY_CATEGORY[explicitCategory] ? explicitCategory : "";
            const category = requestedCategory || String(metadata?.default_category ?? "").toLowerCase().trim();
            if (!category || !MODEL_BY_CATEGORY[category]) {
                return;
            }
            args.category = category;
            const model = MODEL_BY_CATEGORY[category];
            const stamp = formatTimestamp(new Date());
            const modelHintPrompt = formatHeader("MODEL ROUTING", `Preferred category=${category}; model=${model.model}; reasoning=${model.reasoning}; fallback_policy=${metadata?.fallback_policy ?? "openai-default-with-alt-fallback"}.`, stamp.full);
            const modelHintDescription = formatHeader("MODEL ROUTING", `Preferred category=${category}; model=${model.model}; reasoning=${model.reasoning}; fallback_policy=${metadata?.fallback_policy ?? "openai-default-with-alt-fallback"}.`);
            const allowedTools = normalizeToolList(metadata?.allowed_tools);
            const toolSurface = formatHeader("TOOL SURFACE", `subagent=${subagentType}; allowed=${allowedTools.join(",") || "none"}; denied=${deniedTools.join(",") || "none"}.`);
            const routeHint = routeSource !== "explicit_subagent_type"
                ? formatHeader("DELEGATION ROUTER", `inferred subagent_type=${subagentType} from delegation intent.`)
                : "";
            const composedPromptHint = [modelHintPrompt, routeHint, toolSurface]
                .filter((part) => part.length > 0)
                .join("\n");
            const composedDescriptionHint = [modelHintDescription, routeHint, toolSurface]
                .filter((part) => part.length > 0)
                .join("\n");
            const flowHint = formatHeader("SESSION FLOW", `parent_session_id=${sid || "unknown"}; trace_id=${traceId}`);
            const subagentLabel = formatSubagentLabel(subagentType, model.reasoning, stamp.full);
            const cleanPrompt = stripInjectedHeaders(String(args.prompt ?? ""));
            const cleanDescription = stripInjectedHeaders(String(args.description ?? ""));
            args.prompt = prependHint(prependHint(cleanPrompt, flowHint), composedPromptHint);
            args.description = prependHint(prependHint(prependHint(cleanDescription, composedDescriptionHint), flowHint), subagentLabel);
            writeGatewayEventAudit(directory, {
                hook: "agent-model-resolver",
                stage: "state",
                reason_code: "agent_model_routing_hint_injected",
                session_id: sid,
                trace_id: traceId,
                subagent_type: subagentType,
                recommended_category: category,
                model: model.model,
                reasoning: model.reasoning,
                route_source: routeSource,
                tool_surface_injected: "true",
            });
        },
    };
}
