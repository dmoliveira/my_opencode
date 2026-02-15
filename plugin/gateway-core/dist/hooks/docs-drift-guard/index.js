import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { changedPathsFromToolPayload } from "../path-tracking/changed-paths.js";
// Resolves stable session id from tool payload.
function resolveSessionId(payload) {
    const direct = payload.input?.sessionID;
    if (typeof direct === "string" && direct.trim()) {
        return direct.trim();
    }
    const fallback = payload.input?.sessionId;
    if (typeof fallback === "string" && fallback.trim()) {
        return fallback.trim();
    }
    const info = payload.properties?.info?.id;
    if (typeof info === "string" && info.trim()) {
        return info.trim();
    }
    return "";
}
// Converts glob-like pattern to regular expression.
function globRegex(pattern) {
    const escaped = pattern
        .trim()
        .replace(/[|\\{}()[\]^$+?.]/g, "\\$&")
        .replace(/\*\*/g, "::DOUBLE_STAR::")
        .replace(/\*/g, "[^/]*")
        .replace(/::DOUBLE_STAR::/g, ".*");
    return new RegExp(`^${escaped}$`);
}
// Returns normalized slash path for matching.
function normalizePath(path) {
    return path.trim().replace(/\\/g, "/").replace(/^\.\//, "");
}
// Returns true when any path matches a compiled pattern list.
function hasPatternMatch(paths, patterns) {
    for (const path of paths) {
        const normalized = normalizePath(path);
        for (const pattern of patterns) {
            if (pattern.test(normalized)) {
                return true;
            }
        }
    }
    return false;
}
// Returns true when command should trigger doc drift check.
function isGateCommand(command) {
    const value = command.trim().toLowerCase();
    if (!value) {
        return false;
    }
    return /\bgit\s+commit\b/.test(value) || /\bgh\s+pr\s+create\b/.test(value);
}
// Creates docs drift guard that requires docs updates when source changes.
export function createDocsDriftGuardHook(options) {
    const touchedPathsBySession = new Map();
    const sourceRegexes = options.sourcePatterns.map(globRegex);
    const docsRegexes = options.docsPatterns.map(globRegex);
    return {
        id: "docs-drift-guard",
        priority: 430,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted") {
                const sid = resolveSessionId((payload ?? {}));
                if (sid) {
                    touchedPathsBySession.delete(sid);
                }
                return;
            }
            if (type !== "tool.execute.before") {
                return;
            }
            const eventPayload = (payload ?? {});
            const sid = resolveSessionId(eventPayload);
            if (!sid) {
                return;
            }
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const touched = changedPathsFromToolPayload(eventPayload);
            if (touched.length > 0) {
                const next = touchedPathsBySession.get(sid) ?? new Set();
                for (const path of touched) {
                    next.add(normalizePath(path));
                }
                touchedPathsBySession.set(sid, next);
            }
            const command = String(eventPayload.output?.args?.command ?? "");
            if (!isGateCommand(command)) {
                return;
            }
            const allTouched = [...(touchedPathsBySession.get(sid) ?? new Set())];
            if (allTouched.length === 0) {
                return;
            }
            const hasSource = hasPatternMatch(allTouched, sourceRegexes);
            if (!hasSource) {
                return;
            }
            const hasDocs = hasPatternMatch(allTouched, docsRegexes);
            if (hasDocs) {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "docs-drift-guard",
                stage: "skip",
                reason_code: "docs_update_missing",
                session_id: sid,
            });
            if (options.blockOnDrift) {
                throw new Error("[docs-drift-guard] Source changes detected without docs updates. Update README/docs before commit/PR.");
            }
        },
    };
}
