import { writeGatewayEventAudit } from "../../audit/event-audit.js";
// Resolves stable session id across tool lifecycle payloads.
function sessionId(payload) {
    const values = [payload.input?.sessionID, payload.input?.sessionId, payload.properties?.info?.id];
    for (const value of values) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Creates read budget optimizer hook for reducing tiny repeated file reads.
export function createReadBudgetOptimizerHook(options) {
    const trackers = new Map();
    const smallLimit = options.smallReadLimit > 0 ? options.smallReadLimit : 80;
    const maxStreak = options.maxConsecutiveSmallReads > 1 ? options.maxConsecutiveSmallReads : 3;
    return {
        id: "read-budget-optimizer",
        priority: 333,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    trackers.delete(sid);
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "read") {
                    return;
                }
                const sid = sessionId(eventPayload);
                if (!sid) {
                    return;
                }
                const path = String(eventPayload.output?.args?.filePath ?? "").trim();
                const limit = Number(eventPayload.output?.args?.limit ?? smallLimit);
                const tracker = trackers.get(sid) ?? { path, streak: 0, suggest: false };
                if (!path || !Number.isFinite(limit) || limit > smallLimit) {
                    tracker.path = path;
                    tracker.streak = 0;
                    tracker.suggest = false;
                    trackers.set(sid, tracker);
                    return;
                }
                if (tracker.path === path) {
                    tracker.streak += 1;
                }
                else {
                    tracker.path = path;
                    tracker.streak = 1;
                }
                tracker.suggest = tracker.streak >= maxStreak;
                trackers.set(sid, tracker);
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "read") {
                return;
            }
            if (typeof eventPayload.output?.output !== "string") {
                return;
            }
            const sid = sessionId(eventPayload);
            if (!sid) {
                return;
            }
            const tracker = trackers.get(sid);
            if (!tracker?.suggest) {
                return;
            }
            eventPayload.output.output +=
                "\n\n[read-budget-optimizer] Repeated small reads detected on the same file. Prefer larger windows or `grep` first to reduce token usage.";
            tracker.suggest = false;
            trackers.set(sid, tracker);
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "read-budget-optimizer",
                stage: "state",
                reason_code: "small_read_streak_detected",
                session_id: sid,
            });
        },
    };
}
