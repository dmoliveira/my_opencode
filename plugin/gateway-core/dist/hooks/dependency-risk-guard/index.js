import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { join } from "node:path";
import { AuthorizationLedger, AUTH_REQUEST, SETUP_REQUEST, MAX_STATE, PENDING_MS, PERMIT_MS } from "./protocol.js";
import { capability } from "./capability.js";
import { capture, recapture, captureAuditor, digest, exists, runnerCommand } from "./safety.js";
// Resolves file path from write/edit tool args.
function targetPath(payload) {
    const args = payload.output?.args;
    return String(args?.filePath ?? args?.path ?? args?.file_path ?? "").trim();
}
/** Accept only the exact mandatory runtime prefix for this actual session. */
export function nativeDependencyCommand(command, session) {
    const prefix = `OPENCODE_SESSION_ID='${session.replace(/'/g, `'"'"'`)}' `;
    return session && command.startsWith(prefix) ? { command: command.slice(prefix.length), prefix } : { command, prefix: "" };
}
/** Instrumented command guard, not a sandbox for arbitrary user-authored programs. */
export function dependencyCommandRisk(command) {
    const normalized = command.replace(/[\\'"]/g, "").trim();
    if (/dependency-security|dependency-authority-|dependency-risk-guard\/(?:runner|safety|capability|protocol|index)\.[jt]s\b/i.test(normalized))
        return true;
    if (!/\b(?:uv|npm|npx|pnpm|yarn|pip|pip3|poetry)\b/i.test(normalized))
        return false;
    if (/[;|&$`()<>\r\n]/.test(normalized))
        return true;
    if (/^(?:uv|npm|pnpm|yarn|pip|pip3|poetry)\s+(?:--version|--help|-V|-h)$/.test(normalized))
        return false;
    if (/^uv\s+(?:(?:sync|add|remove|lock|run|export|venv|build|publish)|(?:pip|tool|python)\s+[a-z-]+)\s+(?:--help|-h)$/.test(normalized))
        return false;
    if (/^uv\s+(?:pip\s+(?:list|freeze|check)|(?:tool|python)\s+list)$/.test(normalized))
        return false;
    if (/^npm\s+(?:--prefix\s+[^\s]+\s+)?run\s+(?:build|lint|test)$/.test(normalized))
        return false;
    return true;
}
// Creates dependency risk guard requiring explicit handling for lockfile edits.
export function createDependencyRiskGuardHook(options) {
    const ledger = new AuthorizationLedger();
    const capabilities = new Map();
    const bindings = new Map();
    const clear = (session) => {
        ledger.clear(session || undefined);
        for (const key of bindings.keys())
            if (!session || key === session)
                bindings.delete(key);
        for (const [key, value] of capabilities)
            if (!session || session === key) {
                value.close();
                capabilities.delete(key);
            }
    };
    const patterns = [...options.lockfilePatterns, "uv.lock"].map((item) => item.trim()).filter(Boolean);
    const commandPatterns = options.commandPatterns
        .map((item) => {
        try {
            return new RegExp(item, "i");
        }
        catch {
            return null;
        }
    })
        .filter((value) => value !== null);
    return {
        id: "dependency-risk-guard",
        priority: 415,
        events: ["tool.execute.before", "tool.execute.before.final", "tool.execute.after", "tool.execute.before.error", "session.deleted", "session.compacted"],
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            const eventPayload = (payload ?? {});
            ledger.sweep();
            for (const [sid, value] of capabilities)
                if (value.until <= Date.now()) {
                    value.close();
                    capabilities.delete(sid);
                }
            for (const [sid, value] of bindings)
                if (value.until <= Date.now()) {
                    clear(sid);
                }
            const session = eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? eventPayload.properties?.info?.id ?? eventPayload.properties?.sessionID ?? "";
            const call = eventPayload.input?.callID ?? eventPayload.input?.callId ?? "";
            const directory = eventPayload.directory ?? options.directory;
            if (type === "tool.execute.before.final") {
                const expected = bindings.get(session);
                if (!expected || expected.kind === "audit-authority")
                    return;
                try {
                    if (expected.call !== call || expected.command !== eventPayload.output?.args?.command || expected.snapshot.root !== directory)
                        throw new Error("mismatch");
                    recapture(expected.snapshot);
                    if (exists(join(directory, ".venv")))
                        throw new Error("environment_exists");
                    if (expected.kind === "inflight-setup" && captureAuditor(expected.auditorRoot, expected.snapshot).fingerprint !== expected.auditorFingerprint)
                        throw new Error("auditor_changed");
                }
                catch {
                    clear(session);
                    throw new Error("dependency_authorization_final_command_mismatch");
                }
                return;
            }
            if (type === "session.deleted" || type === "session.compacted" || type === "tool.execute.before.error") {
                clear(session);
                return;
            }
            if (type === "tool.execute.after") {
                if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash")
                    return;
                try {
                    if (!session || !call) {
                        clear(session);
                        return;
                    }
                    const bound = bindings.get(session);
                    if (!bound || bound.kind !== "inflight-audit" || bound.call !== call || bound.snapshot.root !== directory) {
                        clear(session);
                        return;
                    }
                    const snapshot = recapture(bound.snapshot);
                    const granted = ledger.finish({ session, call, root: snapshot.root, fingerprint: snapshot.fingerprint }, eventPayload.input?.args?.command, eventPayload.output?.metadata?.exit, eventPayload.output?.output, (frame) => {
                        if (captureAuditor(frame.auditorRoot, snapshot).fingerprint !== frame.auditorFingerprint)
                            throw new Error("auditor_changed");
                    });
                    if (!granted) {
                        clear(session);
                        return;
                    }
                    bindings.set(session, { kind: "audit-authority", snapshot, until: Date.now() + PERMIT_MS });
                    capabilities.get(session)?.close();
                    capabilities.delete(session);
                }
                catch {
                    clear(session);
                }
                return;
            }
            const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
            if (tool === "bash") {
                const rawCommand = String(eventPayload.output?.args?.command ?? "");
                const { command, prefix } = nativeDependencyCommand(rawCommand, session);
                const rewritten = (value) => prefix + value;
                if (!command) {
                    return;
                }
                if (command === AUTH_REQUEST || command === SETUP_REQUEST) {
                    try {
                        if (!session || !call || eventPayload.output?.args?.workdir && eventPayload.output.args.workdir !== directory)
                            throw new Error("scope_invalid");
                        if (command === AUTH_REQUEST) {
                            const existing = bindings.get(session);
                            if (existing && existing.kind !== "audit-authority")
                                throw new Error("authorization_conflict");
                            clear(session);
                            const snapshot = capture(directory);
                            if (exists(join(snapshot.root, ".venv")))
                                throw new Error("environment_exists");
                            const scope = { session, call, root: snapshot.root, fingerprint: snapshot.fingerprint };
                            const pending = ledger.begin(scope, (nonce) => rewritten(runnerCommand(snapshot, "audit", nonce)));
                            bindings.set(session, { kind: "inflight-audit", snapshot, call, command: pending.command, until: pending.until });
                            eventPayload.output.args.command = pending.command;
                        }
                        else {
                            // Consume before any await: concurrent calls and failed permission checks cannot replay.
                            const bound = bindings.get(session);
                            if (!bound || bound.kind !== "audit-authority" || bound.snapshot.root !== directory)
                                throw new Error("authorization_required");
                            const scope = { session, call, root: directory, fingerprint: bound.snapshot.fingerprint };
                            const authority = ledger.consume(scope);
                            const snapshot = recapture(bound.snapshot);
                            if (exists(join(snapshot.root, ".venv")))
                                throw new Error("environment_exists");
                            if (!authority.auditorRoot || !authority.auditorFingerprint ||
                                captureAuditor(authority.auditorRoot, snapshot).fingerprint !== authority.auditorFingerprint)
                                throw new Error("auditor_changed");
                            if (capabilities.size >= MAX_STATE)
                                throw new Error("capability_limit");
                            const reservation = { kind: "inflight-setup", snapshot, call, command: "", until: Date.now() + PENDING_MS,
                                auditorRoot: authority.auditorRoot, auditorFingerprint: authority.auditorFingerprint };
                            bindings.set(session, reservation);
                            const permit = await capability(digest(snapshot.fingerprint + authority.auditorFingerprint), () => {
                                if (recapture(snapshot).root !== directory || exists(join(directory, ".venv")) ||
                                    captureAuditor(authority.auditorRoot, snapshot).fingerprint !== authority.auditorFingerprint)
                                    throw new Error("input_changed");
                            });
                            if (bindings.get(session) !== reservation) {
                                permit.close();
                                throw new Error("authorization_cancelled");
                            }
                            capabilities.set(session, permit);
                            reservation.command = rewritten(runnerCommand(snapshot, "setup", permit.nonce, permit.path, authority.auditorRoot, authority.auditorFingerprint));
                            reservation.until = permit.until;
                            eventPayload.output.args.command = reservation.command;
                        }
                        return;
                    }
                    catch {
                        clear(session);
                    }
                }
                const commandHit = command === AUTH_REQUEST || command === SETUP_REQUEST ||
                    dependencyCommandRisk(command) ||
                    commandPatterns.some((pattern) => pattern.test(rawCommand));
                if (!commandHit) {
                    clear(session);
                    return;
                }
            }
            else {
                if (tool === "apply_patch") {
                    const patch = eventPayload.output?.args?.patchText ?? eventPayload.output?.args?.patch ?? "";
                    if (!patterns.some((pattern) => patch.includes(pattern)))
                        return;
                }
                else {
                    if (tool !== "write" && tool !== "edit") {
                        return;
                    }
                    const filePath = targetPath(eventPayload);
                    if (!filePath) {
                        return;
                    }
                    const hit = patterns.some((pattern) => filePath.endsWith(pattern));
                    if (!hit) {
                        return;
                    }
                }
            }
            clear(session);
            const sessionId = String(eventPayload.input?.sessionID ?? eventPayload.input?.sessionId ?? "");
            writeGatewayEventAudit(directory, {
                hook: "dependency-risk-guard",
                stage: "skip",
                reason_code: "lockfile_edit_guarded",
                session_id: sessionId,
            });
            throw new Error("Lockfile/dependency edits require explicit security validation. Use the exact dependency-security authorize-uv-sync-locked request; unsupported operations remain denied.");
        },
    };
}
