import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import { join, posix } from "node:path";
import { AuthorizationLedger, AUTH_REQUEST, SETUP_REQUEST, MAX_STATE, PENDING_MS, PERMIT_MS, MetadataLedger, METADATA_CHECK_REQUEST, METADATA_MIGRATE_REQUEST, encodeMetadataInvocation } from "./protocol.js";
import { capability, metadataCapability } from "./capability.js";
import { capture, recapture, captureAuditor, digest, exists, runnerCommand, RUNNER, quote, captureMetadataContext, recaptureMetadataContext, encodeMetadataContext, inspectMetadataPreparation, closeMetadataPreparation, verifyMetadataTransition, verifyMetadataRecovery } from "./safety.js";
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
/** Conservative native patch grammar; hunk content is never an operation target. */
export function patchFileTargets(patch) {
    if (Buffer.byteLength(patch, "utf8") > 4 * 1024 * 1024)
        return null;
    const lines = patch.replace(/\r\n?/g, "\n").trim().split("\n");
    if (lines[0]?.trim() !== "*** Begin Patch" || lines.at(-1)?.trim() !== "*** End Patch")
        return null;
    const targets = [];
    let kind;
    let canMove = false;
    const addTarget = (raw) => {
        const path = raw.trim();
        // Quotes are literal upstream, not shell syntax. Refuse ambiguous spellings.
        if (!path || path.length > 4096 || /[\u0000-\u001f\u007f'"]/.test(path))
            return false;
        targets.push(path);
        return true;
    };
    for (const line of lines.slice(1, -1)) {
        if (["*** Begin Patch", "*** End Patch"].includes(line.trim()))
            return null;
        const header = /^\*\*\* (Add|Update|Delete) File:(.*)$/.exec(line);
        if (header) {
            if (!addTarget(header[2]))
                return null;
            kind = header[1];
            canMove = kind === "Update";
            continue;
        }
        if (line.startsWith("*** Move to:")) {
            if (!canMove || !addTarget(line.slice("*** Move to:".length)))
                return null;
            canMove = false;
            continue;
        }
        canMove = false;
        if (line === "*** End of File" && kind === "Update") {
            kind = undefined;
            continue;
        }
        if (line.startsWith("***"))
            return null;
        if (!line.trim())
            continue;
        if (kind === "Add" && line.startsWith("+"))
            continue;
        if (kind === "Update" && (line.startsWith("@@") || /^[ +\-]/.test(line)))
            continue;
        return null;
    }
    return targets.length ? targets : null;
}
function protectedPatchTarget(path, pattern) {
    const portable = (value) => value.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
    const rawPath = portable(path);
    const rawPattern = portable(pattern);
    // Keep the raw comparison too: normalization must never erase a protected suffix.
    return rawPath.endsWith(rawPattern) || posix.normalize(rawPath).endsWith(posix.normalize(rawPattern));
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
    const metadataLedger = new MetadataLedger();
    const metadataBindings = new Map();
    const metadataCapabilities = new Map();
    const capabilities = new Map();
    const bindings = new Map();
    const clearInstall = (session) => {
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
    const clearMetadata = (session) => {
        metadataLedger.clear(session || undefined);
        for (const [sid, value] of metadataBindings)
            if (!session || sid === session) {
                if (value.kind !== "metadata-authority" && value.prepared)
                    closeMetadataPreparation(value.prepared);
                metadataBindings.delete(sid);
            }
        for (const [sid, value] of metadataCapabilities)
            if (!session || sid === session) {
                value.close();
                metadataCapabilities.delete(sid);
            }
    };
    const clear = (session) => { clearInstall(session); clearMetadata(session); };
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
        events: ["tool.execute.before", "tool.execute.before.final", "tool.execute.after", "tool.execute.before.error", "tool.execute.after.error", "session.deleted", "session.compacted"],
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            const eventPayload = (payload ?? {});
            ledger.sweep();
            metadataLedger.sweep();
            for (const [sid, value] of metadataBindings)
                if (value.until <= Date.now())
                    clearMetadata(sid);
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
                const metadata = metadataBindings.get(session);
                if (metadata && metadata.kind !== "metadata-authority") {
                    try {
                        if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash" || metadata.pending.call !== call ||
                            metadata.pending.command !== eventPayload.output?.args?.command || metadata.context.snapshot.root !== directory ||
                            eventPayload.output?.args?.workdir && eventPayload.output.args.workdir !== directory)
                            throw new Error("metadata_final_mismatch");
                        recaptureMetadataContext(metadata.context);
                        metadata.finalChecked = true;
                    }
                    catch {
                        clear(session);
                        throw new Error("dependency_metadata_final_command_mismatch");
                    }
                    return;
                }
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
            if (type === "tool.execute.after.error") {
                // Internal cancellation must never turn missing identity into a global clear.
                if (session)
                    clear(session);
                return;
            }
            if (type === "session.deleted" || type === "session.compacted" || type === "tool.execute.before.error") {
                clear(session);
                return;
            }
            if (type === "tool.execute.after") {
                if (String(eventPayload.input?.tool ?? "").toLowerCase() !== "bash")
                    return;
                const metadata = metadataBindings.get(session);
                if (metadata) {
                    try {
                        if (!session || !call || metadata.kind === "metadata-authority" || !metadata.finalChecked ||
                            metadata.pending.call !== call || metadata.context.snapshot.root !== directory)
                            throw new Error("metadata_result_mismatch");
                        if (metadata.kind === "metadata-check")
                            recaptureMetadataContext(metadata.context);
                        else {
                            if (!metadata.prepared)
                                throw new Error("metadata_outcome_indeterminate");
                            verifyMetadataRecovery(metadata.prepared);
                            verifyMetadataTransition(metadata.context, metadata.prepared.candidate, metadata.pending.candidate);
                        }
                        const frame = metadataLedger.finish({ session, call, root: directory, fingerprint: metadata.context.fingerprint }, eventPayload.input?.args?.command, eventPayload.output?.metadata?.exit, eventPayload.output?.output);
                        if (!frame)
                            throw new Error("metadata_result_invalid");
                        if (metadata.kind === "metadata-check") {
                            metadataBindings.set(session, { kind: "metadata-authority", context: metadata.context, until: Date.now() + PERMIT_MS });
                        }
                        else
                            clearMetadata(session);
                    }
                    catch {
                        clear(session);
                    }
                    return;
                }
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
                if (command === METADATA_CHECK_REQUEST || command === METADATA_MIGRATE_REQUEST) {
                    const install = bindings.get(session);
                    clearInstall(session); // Rejected metadata requests also revoke all installation authority.
                    try {
                        if (!prefix || !session || !call || install && install.kind !== "audit-authority" ||
                            eventPayload.output?.args?.workdir && eventPayload.output.args.workdir !== directory)
                            throw new Error("metadata_scope_invalid");
                        const current = metadataBindings.get(session);
                        if (current && current.kind !== "metadata-authority")
                            throw new Error("metadata_conflict");
                        if (command === METADATA_CHECK_REQUEST) {
                            clearMetadata(session);
                            const context = captureMetadataContext(directory);
                            const pending = metadataLedger.begin({ session, call, root: directory, fingerprint: context.fingerprint }, context.original.sha256, (nonce) => rewritten([context.snapshot.node, RUNNER, "metadata", encodeMetadataInvocation({ v: 1, phase: "check", session, call,
                                    issuer: "", root: directory, fingerprint: context.fingerprint, nonce, original: context.original.sha256, candidate: "",
                                    context: encodeMetadataContext(context), socket: "", capability: "" })].map(quote).join(" ")));
                            metadataBindings.set(session, { kind: "metadata-check", context, pending, finalChecked: false, until: pending.until });
                            eventPayload.output.args.command = pending.command;
                        }
                        else {
                            if (!current || current.kind !== "metadata-authority" || current.context.snapshot.root !== directory)
                                throw new Error("metadata_required");
                            const context = current.context;
                            const pending = metadataLedger.consume({ session, call, root: directory, fingerprint: context.fingerprint });
                            const reservation = { kind: "metadata-migrate", context, pending, finalChecked: false, until: pending.until };
                            metadataBindings.set(session, reservation); // Reserve synchronously, before capability creation yields.
                            recaptureMetadataContext(context);
                            if (metadataCapabilities.size >= MAX_STATE)
                                throw new Error("metadata_capacity");
                            const permit = await metadataCapability(pending, () => {
                                if (metadataBindings.get(session) !== reservation || !reservation.finalChecked || reservation.until <= Date.now() ||
                                    !pending.command || reservation.prepared)
                                    throw new Error("metadata_reservation_cancelled");
                                reservation.prepared = inspectMetadataPreparation(context, pending.nonce, pending.candidate);
                            });
                            if (metadataBindings.get(session) !== reservation) {
                                permit.close();
                                throw new Error("metadata_cancelled");
                            }
                            metadataCapabilities.set(session, permit);
                            pending.command = rewritten([context.snapshot.node, RUNNER, "metadata", encodeMetadataInvocation({ v: 1, phase: "migrate", session, call,
                                    issuer: pending.issuer, root: directory, fingerprint: context.fingerprint, nonce: pending.nonce, original: pending.original,
                                    candidate: pending.candidate, context: encodeMetadataContext(context), socket: permit.path, capability: permit.nonce })].map(quote).join(" "));
                            pending.until = reservation.until = permit.until;
                            eventPayload.output.args.command = pending.command;
                        }
                        return;
                    }
                    catch {
                        clear(session);
                    }
                }
                if (command === AUTH_REQUEST || command === SETUP_REQUEST) {
                    try {
                        const metadata = metadataBindings.get(session);
                        clearMetadata(session);
                        if (metadata && metadata.kind !== "metadata-authority")
                            throw new Error("authorization_conflict");
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
                    const targets = patchFileTargets(patch);
                    if (targets && !targets.some((path) => patterns.some((pattern) => protectedPatchTarget(path, pattern))))
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
