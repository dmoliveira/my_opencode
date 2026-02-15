import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { changedPathsFromToolPayload } from "../path-tracking/changed-paths.js";
// Resolves stable session id from tool and session events.
function sessionId(payload) {
    const direct = payload.input?.sessionID;
    if (typeof direct === "string" && direct.trim()) {
        return direct.trim();
    }
    const fallback = payload.input?.sessionId;
    if (typeof fallback === "string" && fallback.trim()) {
        return fallback.trim();
    }
    const deleted = payload.properties?.info?.id;
    if (typeof deleted === "string" && deleted.trim()) {
        return deleted.trim();
    }
    return "";
}
// Returns glob matcher regular expression.
function globRegex(pattern) {
    const escaped = pattern
        .trim()
        .replace(/[|\\{}()[\]^$+?.]/g, "\\$&")
        .replace(/\*\*/g, "::DOUBLE_STAR::")
        .replace(/\*/g, "[^/]*")
        .replace(/::DOUBLE_STAR::/g, ".*");
    return new RegExp(`^${escaped}$`);
}
// Returns true when command opens commit or PR gating step.
function isGateCommand(command) {
    const value = command.trim().toLowerCase();
    return /\bgit\s+commit\b/.test(value) || /\bgh\s+pr\s+create\b/.test(value);
}
// Creates hook-test parity guard for hook source edits without matching tests.
export function createHookTestParityGuardHook(options) {
    const pathsBySession = new Map();
    const sourceRegexes = options.sourcePatterns.map(globRegex);
    const testRegexes = options.testPatterns.map(globRegex);
    return {
        id: "hook-test-parity-guard",
        priority: 435,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = sessionId((payload ?? {}));
                if (sid) {
                    pathsBySession.delete(sid);
                }
                return;
            }
            if (type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const sid = sessionId(eventPayload);
            if (!sid) {
                return;
            }
            const touched = changedPathsFromToolPayload(eventPayload);
            if (touched.length > 0) {
                const next = pathsBySession.get(sid) ?? new Set();
                for (const path of touched) {
                    next.add(path.trim().replace(/\\/g, "/").replace(/^\.\//, ""));
                }
                pathsBySession.set(sid, next);
            }
            const command = String(eventPayload.output?.args?.command ?? "");
            if (!isGateCommand(command)) {
                return;
            }
            const touchedPaths = [...(pathsBySession.get(sid) ?? new Set())];
            if (touchedPaths.length === 0) {
                return;
            }
            const sourceTouched = touchedPaths.some((path) => sourceRegexes.some((regex) => regex.test(path)));
            if (!sourceTouched) {
                return;
            }
            const testsTouched = touchedPaths.some((path) => testRegexes.some((regex) => regex.test(path)));
            if (testsTouched) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            writeGatewayEventAudit(directory, {
                hook: "hook-test-parity-guard",
                stage: "skip",
                reason_code: "hook_test_parity_missing",
                session_id: sid,
            });
            if (options.blockOnMismatch) {
                throw new Error("[hook-test-parity-guard] Hook source changes detected without matching hook test updates.");
            }
        },
    };
}
