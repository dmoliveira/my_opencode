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
            return candidate;
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
    return best && best.score >= 1 ? best.name : null;
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
            const originalSubagentType = subagentType;
            if (!subagentType) {
                const inferred = inferSubagentType(combinedText, knownAgents);
                if (inferred) {
                    subagentType = inferred;
                    args.subagent_type = inferred;
                }
            }
            if (!subagentType || !knownAgents.has(subagentType)) {
                return;
            }
            const metadata = metadataByAgent.get(subagentType);
            const explicitCategory = String(args.category ?? "").toLowerCase().trim();
            const category = explicitCategory || String(metadata?.default_category ?? "").toLowerCase().trim();
            if (!category || !MODEL_BY_CATEGORY[category]) {
                return;
            }
            if (!explicitCategory) {
                args.category = category;
            }
            const model = MODEL_BY_CATEGORY[category];
            const hint = `[MODEL ROUTING] Preferred category=${category}; model=${model.model}; reasoning=${model.reasoning}; fallback_policy=${metadata?.fallback_policy ?? "openai-default-with-alt-fallback"}.`;
            const allowedTools = normalizeToolList(metadata?.allowed_tools);
            const deniedTools = normalizeToolList(metadata?.denied_tools);
            const toolSurface = `[TOOL SURFACE] subagent=${subagentType}; allowed=${allowedTools.join(",") || "none"}; denied=${deniedTools.join(",") || "none"}.`;
            const discoverability = `[AGENT CATALOG] Inspect details with: /agent-catalog explain ${subagentType}`;
            const routeHint = !originalSubagentType && subagentType
                ? `[DELEGATION ROUTER] inferred subagent_type=${subagentType} from delegation intent.`
                : "";
            const composedHint = [routeHint, hint, toolSurface, discoverability]
                .filter((part) => part.length > 0)
                .join("\n");
            args.prompt = prependHint(String(args.prompt ?? ""), composedHint);
            args.description = prependHint(String(args.description ?? ""), composedHint);
            writeGatewayEventAudit(directory, {
                hook: "agent-model-resolver",
                stage: "state",
                reason_code: "agent_model_routing_hint_injected",
                session_id: sessionId(eventPayload),
                subagent_type: subagentType,
                recommended_category: category,
                model: model.model,
                reasoning: model.reasoning,
                route_source: originalSubagentType ? "explicit_subagent_type" : "inferred_subagent_type",
                tool_surface_injected: "true",
            });
        },
    };
}
