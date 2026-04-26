import { existsSync, readFileSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { loadGatewayState } from "../../state/storage.js";
const SYSTEM_CONTEXT_MARKER = "runtime_session_context:";
const CONCISE_CONTEXT_MARKER = "runtime_concise_mode:";
const VALID_MODES = new Set(["off", "lite", "full", "ultra", "review", "commit"]);
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
function candidateSkillPaths(directory) {
    const home = String(process.env.HOME ?? "").trim() || homedir();
    const candidates = [
        resolve(directory, "skills", "concise-mode", "SKILL.md"),
        resolve(directory, "..", "agents_md", "skills", "concise-mode", "SKILL.md"),
        resolve(directory, "..", "agents.md", "skills", "concise-mode", "SKILL.md"),
        join(home, ".config", "opencode", "agents_md", "skills", "concise-mode", "SKILL.md"),
    ];
    try {
        const siblings = readdirSync(resolve(directory, ".."), { withFileTypes: true });
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
    return candidates;
}
function loadConciseSkillBody(directory) {
    for (const path of candidateSkillPaths(directory)) {
        if (!existsSync(path)) {
            continue;
        }
        try {
            const text = readFileSync(path, "utf-8");
            return text.replace(/^---[\s\S]*?---\s*/, "").trim();
        }
        catch {
            continue;
        }
    }
    return [
        "Use concise/caveman-style communication only when active.",
        "Remove filler and weak hedging first. Keep technical terms, commands, identifiers, filenames, and exact errors unchanged.",
        "lite: concise full sentences. full: terse fragments OK when meaning stays obvious. ultra: strongest safe compression.",
        "Relax concise mode for destructive warnings, security/privacy guidance, or multi-step instructions where clarity matters more than compression.",
    ].join("\n");
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
function buildConciseModeContext(directory, mode, source) {
    return [
        `${CONCISE_CONTEXT_MARKER} ${mode}`,
        `Concise mode active from ${source}.`,
        modeSpecificRules(mode),
        loadConciseSkillBody(directory),
    ].join("\n\n");
}
export function createSessionRuntimeSystemContextHook(options) {
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
            const nextContext = buildSystemContext(sessionId);
            const existingIndex = runtimeContextEntryIndex(system, SYSTEM_CONTEXT_MARKER);
            if (existingIndex >= 0 && system[existingIndex] !== nextContext) {
                system.splice(existingIndex, 1);
            }
            if (runtimeContextEntryIndex(system, SYSTEM_CONTEXT_MARKER) < 0) {
                system.unshift(nextContext);
            }
            const concise = resolveConfiguredConciseMode({
                directory,
                sessionId,
                conciseModeEnabled: options.conciseModeEnabled,
                conciseDefaultMode: options.conciseDefaultMode,
            });
            const conciseIndex = runtimeContextEntryIndex(system, CONCISE_CONTEXT_MARKER);
            if (!concise || concise.mode === "off") {
                if (conciseIndex >= 0) {
                    system.splice(conciseIndex, 1);
                }
                writeGatewayEventAudit(directory, {
                    hook: "session-runtime-system-context",
                    stage: "inject",
                    reason_code: "session_runtime_context_injected_without_concise_mode",
                    session_id: sessionId,
                });
                return;
            }
            const nextConcise = buildConciseModeContext(directory, concise.mode, concise.source);
            if (conciseIndex >= 0) {
                system.splice(conciseIndex, 1);
            }
            system.unshift(nextConcise);
            writeGatewayEventAudit(directory, {
                hook: "session-runtime-system-context",
                stage: "inject",
                reason_code: "session_runtime_context_with_concise_mode_injected",
                session_id: sessionId,
                concise_mode: concise.mode,
                concise_mode_source: concise.source,
            });
        },
    };
}
