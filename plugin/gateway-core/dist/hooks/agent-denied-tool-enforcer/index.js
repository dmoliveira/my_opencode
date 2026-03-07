import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadAgentMetadata } from "../shared/agent-metadata.js";
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim();
}
function referencesDeniedTool(text, tool) {
    const lower = text.toLowerCase();
    const checks = [
        `use ${tool}`,
        `run ${tool}`,
        `execute ${tool}`,
        `call ${tool}`,
        `\`${tool}\``,
        `functions.${tool}`,
        `"${tool}"`,
        `'${tool}'`,
    ];
    return checks.some((pattern) => lower.includes(pattern));
}
function suggestAllowedTool(deniedTool, allowedTools) {
    if (!allowedTools.length) {
        return null;
    }
    const replacementMatrix = {
        bash: ["read", "glob", "grep"],
        write: ["edit", "read"],
        edit: ["read", "write"],
        task: ["read", "glob", "grep"],
        webfetch: ["read", "grep"],
        todowrite: ["todoread", "read"],
    };
    const preferred = replacementMatrix[deniedTool] ?? [];
    for (const candidate of preferred) {
        if (allowedTools.includes(candidate)) {
            return candidate;
        }
    }
    return allowedTools[0] ?? null;
}
export function createAgentDeniedToolEnforcerHook(options) {
    return {
        id: "agent-denied-tool-enforcer",
        priority: 290,
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
            const subagentType = String(args.subagent_type ?? "").toLowerCase().trim();
            if (!subagentType) {
                return;
            }
            const metadata = loadAgentMetadata(directory).get(subagentType);
            const allowed = Array.isArray(metadata?.allowed_tools) ? metadata?.allowed_tools : [];
            const denied = Array.isArray(metadata?.denied_tools) ? metadata?.denied_tools : [];
            if (!denied || denied.length === 0) {
                return;
            }
            const combinedText = `${String(args.prompt ?? "")}\n${String(args.description ?? "")}`;
            const violating = denied.filter((deniedTool) => referencesDeniedTool(combinedText, String(deniedTool).toLowerCase().trim()));
            if (violating.length === 0) {
                return;
            }
            const suggestion = suggestAllowedTool(String(violating[0]), allowed);
            writeGatewayEventAudit(directory, {
                hook: "agent-denied-tool-enforcer",
                stage: "guard",
                reason_code: "tool_surface_enforced_runtime",
                session_id: sessionId(eventPayload),
                subagent_type: subagentType,
                denied_tools: violating.join(","),
                suggested_tool: suggestion ?? undefined,
            });
            throw new Error(`Blocked task delegation for ${subagentType}: prompt requests denied tools (${violating.join(", ")}).${suggestion ? ` Use allowed tool '${suggestion}' instead.` : ""} Remove forbidden tool instructions and retry.`);
        },
    };
}
