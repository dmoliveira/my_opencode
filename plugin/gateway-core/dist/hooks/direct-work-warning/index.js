import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { getDelegationChildSessionLink } from "../shared/delegation-child-session.js";
const WRITE_LIKE_TOOLS = new Set(["write", "edit", "multiedit", "apply_patch"]);
const REMINDER_HEADER = "[direct-work-warning]";
const BLOCK_HEADER = "[direct-work-discipline]";
function sessionId(payload) {
    return String(payload.input?.sessionID ?? payload.input?.sessionId ?? "").trim();
}
function targetPath(payload) {
    return String(payload.output?.args?.filePath ??
        payload.output?.args?.path ??
        payload.output?.args?.file ??
        "").trim();
}
function reminderText(path) {
    const suffix = path ? ` Target: ${path}.` : "";
    return `${REMINDER_HEADER} Direct file edits from the primary orchestrator should be exceptional.${suffix} Prefer delegating implementation first, then verify and integrate the result.`;
}
function blockText(path) {
    const suffix = path ? ` Target: ${path}.` : "";
    return `${BLOCK_HEADER} Repeated direct file edits from the primary orchestrator are blocked for this session.${suffix} Delegate implementation first, then verify and integrate the result.`;
}
export function createDirectWorkWarningHook(options) {
    const warnedSessions = new Set();
    return {
        id: "direct-work-warning",
        priority: 366,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = String((payload ?? {}).properties?.info?.id ?? "").trim();
                if (sid) {
                    warnedSessions.delete(sid);
                }
                return;
            }
            if (type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const tool = String(eventPayload.input?.tool ?? "")
                .toLowerCase()
                .trim();
            if (!WRITE_LIKE_TOOLS.has(tool)) {
                return;
            }
            const sid = sessionId(eventPayload);
            if (!sid || getDelegationChildSessionLink(sid)) {
                return;
            }
            const path = targetPath(eventPayload);
            if (options.blockRepeatedEdits && warnedSessions.has(sid)) {
                writeGatewayEventAudit(options.directory, {
                    hook: "direct-work-warning",
                    stage: "before",
                    reason_code: "direct_work_repeat_blocked",
                    session_id: sid,
                    tool,
                    file_path: path || undefined,
                });
                throw new Error(blockText(path));
            }
            const reminder = reminderText(path);
            const existing = String(eventPayload.output?.message ?? "");
            if (existing.includes(REMINDER_HEADER)) {
                return;
            }
            eventPayload.output = eventPayload.output ?? {};
            eventPayload.output.message = existing
                ? `${existing}\n${reminder}`
                : reminder;
            writeGatewayEventAudit(options.directory, {
                hook: "direct-work-warning",
                stage: "before",
                reason_code: "direct_work_warning_injected",
                session_id: sid,
                tool,
                file_path: path || undefined,
            });
            warnedSessions.add(sid);
        },
    };
}
