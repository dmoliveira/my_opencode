import { execSync } from "node:child_process";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const CONTEXT_GUARD_PREFIX = "󰚩 Context Guard:";
function isOpencodeCommand(command) {
    const lowered = command.trim().toLowerCase();
    if (!lowered) {
        return false;
    }
    return /(^|[\s/])opencode(\s|$)/.test(lowered);
}
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
function guardPrefix(mode) {
    if (mode === "plain") {
        return "[Context Guard]:";
    }
    if (mode === "both") {
        return "󰚩 Context Guard [Context Guard]:";
    }
    return CONTEXT_GUARD_PREFIX;
}
function pruneSessionStates(states, maxEntries) {
    if (states.size <= maxEntries) {
        return;
    }
    let oldestKey = "";
    let oldestAt = Number.POSITIVE_INFINITY;
    for (const [key, state] of states.entries()) {
        if (state.lastSeenAtMs < oldestAt) {
            oldestAt = state.lastSeenAtMs;
            oldestKey = key;
        }
    }
    if (oldestKey) {
        states.delete(oldestKey);
    }
}
function sampleProcessPressure() {
    const stdout = execSync("ps -axo rss=,command=", {
        encoding: "utf-8",
        stdio: ["ignore", "pipe", "ignore"],
        timeout: 1200,
    });
    let opencodeProcessCount = 0;
    let continueProcessCount = 0;
    let maxRssMb = 0;
    for (const rawLine of stdout.split("\n")) {
        const line = rawLine.trim();
        if (!line) {
            continue;
        }
        const firstSpace = line.indexOf(" ");
        if (firstSpace <= 0) {
            continue;
        }
        const rssToken = line.slice(0, firstSpace).trim();
        const command = line.slice(firstSpace + 1).trim().toLowerCase();
        if (!isOpencodeCommand(command)) {
            continue;
        }
        opencodeProcessCount += 1;
        if (command.includes("--continue")) {
            continueProcessCount += 1;
        }
        const rssKb = Number.parseInt(rssToken, 10);
        if (Number.isFinite(rssKb) && rssKb > 0) {
            const rssMb = rssKb / 1024;
            if (rssMb > maxRssMb) {
                maxRssMb = rssMb;
            }
        }
    }
    return {
        opencodeProcessCount,
        continueProcessCount,
        maxRssMb,
    };
}
export function createGlobalProcessPressureHook(options) {
    const sessionStates = new Map();
    let globalToolCalls = 0;
    let lastCheckedAtToolCall = 0;
    let lastSample = null;
    const runSample = options.sampler ?? sampleProcessPressure;
    return {
        id: "global-process-pressure",
        priority: 275,
        async event(type, payload) {
            if (!options.enabled || type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId || typeof eventPayload.output?.output !== "string") {
                return;
            }
            globalToolCalls += 1;
            const priorState = sessionStates.get(sessionId) ?? {
                lastWarnedAtToolCall: 0,
                lastSeenAtMs: Date.now(),
            };
            const nextState = {
                ...priorState,
                lastSeenAtMs: Date.now(),
            };
            sessionStates.set(sessionId, nextState);
            pruneSessionStates(sessionStates, options.maxSessionStateEntries);
            const shouldSample = lastSample === null ||
                globalToolCalls - lastCheckedAtToolCall >= options.checkCooldownToolCalls;
            if (shouldSample) {
                try {
                    lastSample = runSample();
                    lastCheckedAtToolCall = globalToolCalls;
                }
                catch {
                    writeGatewayEventAudit(directory, {
                        hook: "global-process-pressure",
                        stage: "skip",
                        reason_code: "global_pressure_sample_failed",
                        session_id: sessionId,
                    });
                    return;
                }
            }
            else {
                writeGatewayEventAudit(directory, {
                    hook: "global-process-pressure",
                    stage: "skip",
                    reason_code: "global_pressure_check_cooldown",
                    session_id: sessionId,
                });
            }
            const sample = lastSample;
            if (!sample) {
                return;
            }
            const thresholdExceeded = sample.continueProcessCount >= options.warningContinueSessions ||
                sample.opencodeProcessCount >= options.warningOpencodeProcesses ||
                sample.maxRssMb >= options.warningMaxRssMb;
            if (!thresholdExceeded) {
                writeGatewayEventAudit(directory, {
                    hook: "global-process-pressure",
                    stage: "skip",
                    reason_code: "global_pressure_below_threshold",
                    session_id: sessionId,
                });
                return;
            }
            if (nextState.lastWarnedAtToolCall > 0 &&
                globalToolCalls - nextState.lastWarnedAtToolCall < options.reminderCooldownToolCalls) {
                writeGatewayEventAudit(directory, {
                    hook: "global-process-pressure",
                    stage: "skip",
                    reason_code: "global_pressure_reminder_cooldown",
                    session_id: sessionId,
                });
                return;
            }
            const outputText = eventPayload.output.output;
            if (outputText.includes("[ERROR]") ||
                outputText.includes("[TOOL OUTPUT TRUNCATED]")) {
                writeGatewayEventAudit(directory, {
                    hook: "global-process-pressure",
                    stage: "skip",
                    reason_code: "global_pressure_output_append_skipped",
                    session_id: sessionId,
                });
                return;
            }
            const prefix = guardPrefix(options.guardMarkerMode);
            if (options.guardVerbosity === "minimal") {
                eventPayload.output.output = `${outputText}\n\n${prefix} Global process pressure is high.`;
            }
            else if (options.guardVerbosity === "debug") {
                eventPayload.output.output = `${outputText}\n\n${prefix} Global process pressure is high.\n[continue_sessions=${sample.continueProcessCount}, opencode_processes=${sample.opencodeProcessCount}, max_rss_mb=${sample.maxRssMb.toFixed(1)}]`;
            }
            else {
                eventPayload.output.output = `${outputText}\n\n${prefix} Global process pressure is high; memory risk increases with many concurrent sessions.`;
            }
            sessionStates.set(sessionId, {
                ...nextState,
                lastWarnedAtToolCall: globalToolCalls,
            });
            writeGatewayEventAudit(directory, {
                hook: "global-process-pressure",
                stage: "state",
                reason_code: "global_process_pressure_warning_appended",
                session_id: sessionId,
                continue_sessions: sample.continueProcessCount,
                opencode_processes: sample.opencodeProcessCount,
                max_rss_mb: Number(sample.maxRssMb.toFixed(1)),
            });
        },
    };
}
