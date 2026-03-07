import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata } from "../shared/agent-metadata.js";
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
function formatSubagentLabel(subagentType, reasoning) {
    const icon = SUBAGENT_ICON_BY_TYPE[subagentType] ?? {
        nerd: "󰚩",
        fallback: "[agent]",
    };
    return `[SUBAGENT] ${icon.nerd} ${subagentType} ${icon.fallback} | effort=${reasoning}`;
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
                const inferred = inferSubagentType(combinedText, knownAgents);
                const explicitScore = scoreSubagentIntent(combinedText, subagentType);
                if (inferred && inferred.name !== subagentType && inferred.score > explicitScore) {
                    const previous = subagentType;
                    subagentType = inferred.name;
                    args.subagent_type = inferred.name;
                    routeSource = "overridden_low_confidence";
                    writeGatewayEventAudit(directory, {
                        hook: "agent-model-resolver",
                        stage: "guard",
                        reason_code: "delegation_route_overridden_low_confidence",
                        session_id: sessionId(eventPayload),
                        original_subagent_type: previous,
                        inferred_subagent_type: inferred.name,
                        original_score: String(explicitScore),
                        inferred_score: String(inferred.score),
                    });
                }
            }
            if (!subagentType || !knownAgents.has(subagentType)) {
                return;
            }
            const metadata = metadataByAgent.get(subagentType);
            const explicitCategory = String(args.category ?? "").toLowerCase().trim();
            const requestedCategory = explicitCategory && MODEL_BY_CATEGORY[explicitCategory] ? explicitCategory : "";
            const category = requestedCategory || String(metadata?.default_category ?? "").toLowerCase().trim();
            if (!category || !MODEL_BY_CATEGORY[category]) {
                return;
            }
            args.category = category;
            const model = MODEL_BY_CATEGORY[category];
            const hint = `[MODEL ROUTING] Preferred category=${category}; model=${model.model}; reasoning=${model.reasoning}; fallback_policy=${metadata?.fallback_policy ?? "openai-default-with-alt-fallback"}.`;
            const allowedTools = normalizeToolList(metadata?.allowed_tools);
            const deniedTools = normalizeToolList(metadata?.denied_tools);
            const toolSurface = `[TOOL SURFACE] subagent=${subagentType}; allowed=${allowedTools.join(",") || "none"}; denied=${deniedTools.join(",") || "none"}.`;
            const routeHint = routeSource !== "explicit_subagent_type"
                ? `[DELEGATION ROUTER] inferred subagent_type=${subagentType} from delegation intent.`
                : "";
            const composedHint = [routeHint, hint, toolSurface]
                .filter((part) => part.length > 0)
                .join("\n");
            const subagentLabel = formatSubagentLabel(subagentType, model.reasoning);
            args.prompt = prependHint(String(args.prompt ?? ""), composedHint);
            args.description = prependHint(prependHint(String(args.description ?? ""), composedHint), subagentLabel);
            writeGatewayEventAudit(directory, {
                hook: "agent-model-resolver",
                stage: "state",
                reason_code: "agent_model_routing_hint_injected",
                session_id: sessionId(eventPayload),
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
