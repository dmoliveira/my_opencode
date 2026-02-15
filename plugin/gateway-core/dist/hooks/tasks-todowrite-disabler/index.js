import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const BLOCKED_TOOLS = new Set(["task", "tasks", "todowrite"]);
// Creates hook that blocks task/todowrite tools to avoid external tracker conflicts.
export function createTasksTodowriteDisablerHook(options) {
    return {
        id: "tasks-todowrite-disabler",
        priority: 330,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "";
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (!BLOCKED_TOOLS.has(tool)) {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "tasks-todowrite-disabler",
                stage: "skip",
                reason_code: "task_or_todowrite_blocked",
                session_id: String(sessionId),
                tool,
            });
            throw new Error("Task/TodoWrite tools are disabled in this workflow. Use br issue tracking and Agent Mail coordination instead.");
        },
    };
}
