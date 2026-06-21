import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { REASON_CODES } from "../../bridge/reason-codes.js";
import { loadGatewayState } from "../../state/storage.js";
const SYSTEM_CONTEXT_MARKER = "runtime_session_context:";
const CONCISE_CONTEXT_MARKER = "runtime_concise_mode:";
const VALID_MODES = new Set(["off", "lite", "full", "ultra", "review", "commit"]);
const DEFAULT_CONCISE_SKILL_BODY = [
    "Use concise/caveman-style communication only when active.",
    "Remove filler and weak hedging first. Keep technical terms, commands, identifiers, filenames, and exact errors unchanged.",
    "lite: concise full sentences. full: terse fragments OK when meaning stays obvious. ultra: strongest safe compression.",
    "Relax concise mode for destructive warnings, security/privacy guidance, or multi-step instructions where clarity matters more than compression.",
].join("\n");
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function runtimeContextEntryIndex(system, marker) {
    return system.findIndex((entry) => typeof entry === "string" && entry.includes(marker));
}
function pathSignature(path) {
    if (!existsSync(path)) {
        return "missing";
    }
    try {
        const stats = statSync(path);
        return [stats.dev, stats.ino, stats.mode, stats.size, stats.mtimeMs, stats.ctimeMs].join(":");
    }
    catch {
        return "missing";
    }
}
function buildSystemContext(sessionId) {
    return [
        `${SYSTEM_CONTEXT_MARKER} ${sessionId}`,
        "Use this exact runtime session id for commits, logs, telemetry, and external tooling created during this session.",
        "If the user asks for the current runtime session id, return it exactly.",
    ].join("\n");
}
function resolveConfiguredConciseMode(options) {
    const state = loadGatewayState(options.directory);
    const stateMode = String(state?.conciseMode?.mode ?? "").trim().toLowerCase();
    const stateSessionId = String(state?.conciseMode?.sessionId ?? "").trim();
    if (VALID_MODES.has(stateMode) &&
        stateSessionId === options.sessionId) {
        return { mode: stateMode, source: String(state?.conciseMode?.source ?? "state") };
    }
    if (options.conciseModeEnabled && options.conciseDefaultMode !== "off") {
        return { mode: options.conciseDefaultMode, source: "config_default" };
    }
    return null;
}
function candidateSkillPaths(directory, candidateCacheByDirectory) {
    const home = String(process.env.HOME ?? "").trim() || homedir();
    const siblingsRoot = resolve(directory, "..");
    const siblingSignature = pathSignature(siblingsRoot);
    const cached = candidateCacheByDirectory.get(directory);
    if (cached?.siblingSignature === siblingSignature) {
        return cached.candidates;
    }
    const candidates = [
        resolve(directory, "skills", "concise-mode", "SKILL.md"),
        resolve(directory, "..", "agents_md", "skills", "concise-mode", "SKILL.md"),
        resolve(directory, "..", "agents.md", "skills", "concise-mode", "SKILL.md"),
        join(home, ".config", "opencode", "agents_md", "skills", "concise-mode", "SKILL.md"),
    ];
    try {
        const siblings = readdirSync(siblingsRoot, { withFileTypes: true });
        for (const entry of siblings) {
            if (!entry.isDirectory() || !entry.name.startsWith("agents_md")) {
                continue;
            }
            candidates.push(resolve(directory, "..", entry.name, "skills", "concise-mode", "SKILL.md"));
        }
    }
    catch {
        // best-effort sibling worktree discovery only
    }
    candidateCacheByDirectory.set(directory, {
        siblingSignature,
        candidates,
    });
    return candidates;
}
function loadConciseSkillBody(directory, candidateCacheByDirectory, bodyCacheByPath) {
    for (const path of candidateSkillPaths(directory, candidateCacheByDirectory)) {
        if (!existsSync(path)) {
            continue;
        }
        const signature = pathSignature(path);
        const cached = bodyCacheByPath.get(path);
        if (cached?.signature === signature) {
            return cached.body;
        }
        try {
            const text = readFileSync(path, "utf-8");
            const body = text.replace(/^---[\s\S]*?---\s*/, "").trim();
            bodyCacheByPath.set(path, { signature, body });
            return body;
        }
        catch {
            continue;
        }
    }
    return DEFAULT_CONCISE_SKILL_BODY;
}
function modeSpecificRules(mode) {
    if (mode === "review") {
        return "Use one-line review findings when possible. Put blockers first. Keep remediation direct.";
    }
    if (mode === "commit") {
        return "Draft terse commit messages. Keep why over what. Prefer one compact sentence when it stays accurate.";
    }
    if (mode === "lite") {
        return "Active level: lite. Keep full sentences, but cut filler and pleasantries.";
    }
    if (mode === "ultra") {
        return "Active level: ultra. Maximize safe compression. Expand if terseness would hide risk or meaning.";
    }
    return "Active level: full. Prefer short direct fragments when they stay clear and technically exact.";
}
function buildConciseModeContext(directory, mode, source, candidateCacheByDirectory, bodyCacheByPath) {
    return [
        `${CONCISE_CONTEXT_MARKER} ${mode}`,
        `Concise mode active from ${source}.`,
        modeSpecificRules(mode),
        loadConciseSkillBody(directory, candidateCacheByDirectory, bodyCacheByPath),
    ].join("\n\n");
}
export function createSessionRuntimeSystemContextHook(options) {
    const conciseSkillCandidateCacheByDirectory = new Map();
    const conciseSkillBodyCacheByPath = new Map();
    return {
        id: "session-runtime-system-context",
        priority: 294,
        async event(type, payload) {
            if (!options.enabled || type !== "experimental.chat.system.transform") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            const system = eventPayload.output?.system;
            if (!sessionId || !Array.isArray(system)) {
                return;
            }
            const concise = resolveConfiguredConciseMode({
                directory,
                sessionId,
                conciseModeEnabled: options.conciseModeEnabled,
                conciseDefaultMode: options.conciseDefaultMode,
            });
            const injectSessionIdContext = options.injectSessionIdContext !== false;
            const shouldInjectSessionId = injectSessionIdContext &&
                (!options.injectSessionIdWhenConciseModeOnly || (concise && concise.mode !== "off"));
            const existingIndex = runtimeContextEntryIndex(system, SYSTEM_CONTEXT_MARKER);
            let sessionContextChanged = false;
            if (shouldInjectSessionId) {
                const nextContext = buildSystemContext(sessionId);
                if (existingIndex >= 0 && system[existingIndex] !== nextContext) {
                    system.splice(existingIndex, 1);
                    sessionContextChanged = true;
                }
                if (runtimeContextEntryIndex(system, SYSTEM_CONTEXT_MARKER) < 0) {
                    system.unshift(nextContext);
                    sessionContextChanged = true;
                }
            }
            else if (existingIndex >= 0) {
                system.splice(existingIndex, 1);
                sessionContextChanged = true;
            }
            const conciseIndex = runtimeContextEntryIndex(system, CONCISE_CONTEXT_MARKER);
            const currentConcise = conciseIndex >= 0 ? system[conciseIndex] : "";
            if (!concise || concise.mode === "off") {
                let conciseContextChanged = false;
                if (conciseIndex >= 0) {
                    system.splice(conciseIndex, 1);
                    conciseContextChanged = true;
                }
                const reasonCode = shouldInjectSessionId
                    ? sessionContextChanged || conciseContextChanged
                        ? REASON_CODES.SESSION_RUNTIME_WITHOUT_CONCISE_INJECTED
                        : null
                    : injectSessionIdContext && options.injectSessionIdWhenConciseModeOnly
                        ? sessionContextChanged || conciseContextChanged
                            ? REASON_CODES.SESSION_RUNTIME_SKIPPED_CONCISE_SCOPE
                            : null
                        : sessionContextChanged || conciseContextChanged
                            ? REASON_CODES.SESSION_RUNTIME_WITHOUT_CONCISE_REMOVED
                            : null;
                if (reasonCode) {
                    writeGatewayEventAudit(directory, {
                        hook: "session-runtime-system-context",
                        stage: "inject",
                        reason_code: reasonCode,
                        session_id: sessionId,
                    });
                }
                return;
            }
            const nextConcise = buildConciseModeContext(directory, concise.mode, concise.source, conciseSkillCandidateCacheByDirectory, conciseSkillBodyCacheByPath);
            let conciseContextChanged = false;
            if (currentConcise !== nextConcise) {
                if (conciseIndex >= 0) {
                    system.splice(conciseIndex, 1);
                }
                system.unshift(nextConcise);
                conciseContextChanged = true;
            }
            const reasonCode = shouldInjectSessionId
                ? sessionContextChanged || conciseContextChanged
                    ? REASON_CODES.SESSION_RUNTIME_WITH_CONCISE_INJECTED
                    : null
                : injectSessionIdContext && options.injectSessionIdWhenConciseModeOnly
                    ? null
                    : sessionContextChanged || conciseContextChanged
                        ? REASON_CODES.SESSION_RUNTIME_WITH_CONCISE_SKIPPED
                        : null;
            if (!reasonCode) {
                return;
            }
            writeGatewayEventAudit(directory, {
                hook: "session-runtime-system-context",
                stage: "inject",
                reason_code: reasonCode,
                session_id: sessionId,
                concise_mode: concise.mode,
                concise_mode_source: concise.source,
            });
        },
    };
}
