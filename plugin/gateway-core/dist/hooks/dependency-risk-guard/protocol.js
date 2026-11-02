import { randomBytes } from "node:crypto";
export const AUTH_REQUEST = "dependency-security authorize-uv-sync-locked";
export const SETUP_REQUEST = "uv sync --locked";
export const PENDING_MS = 180_000;
export const PERMIT_MS = 60_000;
export const MAX_STATE = 128;
export const METADATA_CHECK_REQUEST = "dependency-security check-uv-lock-virtual";
export const METADATA_MIGRATE_REQUEST = "dependency-security migrate-uv-lock-virtual";
function validateMetadataBinding(value, checking) {
    const sha = (x) => typeof x === "string" && /^[a-f0-9]{64}$/.test(x);
    const id = (x) => typeof x === "string" && x.length > 0 && x.length <= 256 && !/[\u0000-\u001f\u007f]/.test(x);
    if (!["check", "migrate"].includes(value.phase) || !id(value.session) || !id(value.call) ||
        typeof value.root !== "string" || !value.root.startsWith("/") || value.root.length > 4096 || /[\u0000-\u001f\u007f]/.test(value.root) ||
        !sha(value.fingerprint) || !sha(value.nonce) || !sha(value.original) ||
        (checking ? value.candidate !== "" : !sha(value.candidate) || value.candidate === value.original) ||
        (value.phase === "check" ? value.issuer !== "" : !id(value.issuer) || value.issuer === value.call))
        throw new Error("metadata_binding_invalid");
}
/** Separate grammar: no metadata result can decode as an installation AuditFrame. */
export function parseMetadataFrame(output, expected) {
    if (typeof output !== "string" || Buffer.byteLength(output) > 8192)
        throw new Error("metadata_frame_invalid");
    const frame = JSON.parse(output);
    if (!frame || Object.keys(frame).join(",") !== "v,phase,session,call,issuer,root,fingerprint,nonce,original,candidate" ||
        JSON.stringify(frame) + "\n" !== output || frame.v !== 1)
        throw new Error("metadata_frame_invalid");
    validateMetadataBinding(frame, false);
    for (const key of ["phase", "session", "call", "issuer", "root", "fingerprint", "nonce", "original"]) {
        if (frame[key] !== expected[key])
            throw new Error("metadata_frame_mismatch");
    }
    if (expected.phase === "migrate" && frame.candidate !== expected.candidate)
        throw new Error("metadata_frame_mismatch");
    return frame;
}
export function metadataFrame(binding) {
    validateMetadataBinding(binding, false);
    return { v: 1, phase: binding.phase, session: binding.session, call: binding.call, issuer: binding.issuer,
        root: binding.root, fingerprint: binding.fingerprint, nonce: binding.nonce, original: binding.original, candidate: binding.candidate };
}
export function encodeMetadataInvocation(value) {
    validateMetadataBinding(value, value.phase === "check");
    if (value.v !== 1 || typeof value.context !== "string" || !/^[A-Za-z0-9_-]{1,43691}$/.test(value.context) ||
        (value.phase === "check" ? value.socket !== "" || value.capability !== "" :
            typeof value.socket !== "string" || !value.socket.startsWith("/") || value.socket.length > 4096 ||
                !/^[a-f0-9]{64}$/.test(value.capability)))
        throw new Error("metadata_invocation_invalid");
    const ordered = { v: value.v, phase: value.phase, session: value.session, call: value.call, issuer: value.issuer, root: value.root,
        fingerprint: value.fingerprint, nonce: value.nonce, original: value.original, candidate: value.candidate,
        context: value.context, socket: value.socket, capability: value.capability };
    if (Object.keys(value).sort().join(",") !== Object.keys(ordered).sort().join(","))
        throw new Error("metadata_invocation_invalid");
    return Buffer.from(JSON.stringify(ordered)).toString("base64url");
}
export function decodeMetadataInvocation(encoded) {
    if (!/^[A-Za-z0-9_-]{1,70000}$/.test(encoded))
        throw new Error("metadata_invocation_invalid");
    const value = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
    if (encodeMetadataInvocation(value) !== encoded)
        throw new Error("metadata_invocation_noncanonical");
    return value;
}
/** Host-only metadata authority. Each attempt consumes synchronously, before any await. */
export class MetadataLedger {
    now;
    pending = new Map();
    permits = new Map();
    seen = new Map();
    constructor(now = Date.now) {
        this.now = now;
    }
    clear(session) {
        for (const map of [this.pending, this.permits])
            for (const [key, value] of map)
                if (!session || value.session === session)
                    map.delete(key);
    }
    sweep() {
        for (const map of [this.pending, this.permits])
            for (const [key, value] of map)
                if (value.until <= this.now())
                    map.delete(key);
        for (const [key, until] of this.seen)
            if (until <= this.now())
                this.seen.delete(key);
    }
    reserve(binding, command) {
        if (this.pending.has(binding.session) || this.pending.size + this.permits.size >= MAX_STATE || this.seen.size >= MAX_STATE ||
            this.seen.has(`${binding.session}\0${binding.call}`)) {
            this.clear(binding.session);
            throw new Error("metadata_conflict");
        }
        const pending = { ...binding, command: command(binding.nonce), until: this.now() + PENDING_MS };
        this.seen.set(`${binding.session}\0${binding.call}`, pending.until + PERMIT_MS);
        this.pending.set(binding.session, pending);
        return pending;
    }
    begin(scope, original, command) {
        this.sweep();
        if (this.pending.has(scope.session)) {
            this.clear(scope.session);
            throw new Error("metadata_conflict");
        }
        this.clear(scope.session);
        const binding = { ...scope, phase: "check", issuer: "", original, candidate: "", nonce: randomBytes(32).toString("hex") };
        validateMetadataBinding(binding, true);
        return this.reserve(binding, command);
    }
    consume(scope) {
        this.sweep();
        const permit = this.permits.get(scope.session);
        this.clear(scope.session);
        if (!permit || permit.root !== scope.root || permit.fingerprint !== scope.fingerprint || permit.call === scope.call)
            throw new Error("metadata_required");
        const binding = { ...scope, phase: "migrate", issuer: permit.call, original: permit.original,
            candidate: permit.candidate, nonce: randomBytes(32).toString("hex") };
        validateMetadataBinding(binding, false);
        return this.reserve(binding, () => "");
    }
    finish(scope, command, exit, output) {
        this.sweep();
        const pending = this.pending.get(scope.session);
        this.clear(scope.session);
        if (!pending || pending.call !== scope.call || pending.root !== scope.root || pending.fingerprint !== scope.fingerprint ||
            pending.command !== command || exit !== 0)
            return;
        try {
            const frame = parseMetadataFrame(output, pending);
            if (pending.phase === "check")
                this.permits.set(scope.session, { ...pending, candidate: frame.candidate, until: this.now() + PERMIT_MS });
            return frame;
        }
        catch {
            return;
        }
    }
}
/** Exactly one canonical frame: duplicate keys, chatter and truncated output fail closed. */
export function parseFrame(output, pending) {
    if (typeof output !== "string" || Buffer.byteLength(output) > 2048)
        throw new Error("frame_invalid");
    const value = JSON.parse(output);
    if (!value || Object.keys(value).join(",") !== "v,nonce,fingerprint,packages,closure,auditor,operation,build,auditorRoot,auditorFingerprint" ||
        JSON.stringify(value) + "\n" !== output || value.v !== 1 || value.nonce !== pending.nonce ||
        value.fingerprint !== pending.fingerprint || !Number.isSafeInteger(value.packages) ||
        value.packages < 1 || value.packages > 512 || !/^[a-f0-9]{64}$/.test(value.closure) ||
        value.auditor !== "pip-audit==2.10.1" || value.operation !== "uv-sync-locked" || value.build !== "none" ||
        typeof value.auditorRoot !== "string" || !value.auditorRoot.startsWith("/") || value.auditorRoot.length > 1024 ||
        !/^[a-f0-9]{64}$/.test(value.auditorFingerprint)) {
        throw new Error("frame_invalid");
    }
    return value;
}
/** Host-only, bounded and restart-ephemeral. All transitions are synchronous. */
export class AuthorizationLedger {
    now;
    pending = new Map();
    permits = new Map();
    seen = new Map();
    constructor(now = Date.now) {
        this.now = now;
    }
    clear(session) {
        for (const map of [this.pending, this.permits]) {
            for (const [key, value] of map)
                if (!session || value.session === session)
                    map.delete(key);
        }
    }
    sweep() {
        const now = this.now();
        for (const map of [this.pending, this.permits]) {
            for (const [key, value] of map)
                if (value.until <= now)
                    map.delete(key);
        }
        for (const [key, until] of this.seen)
            if (until <= now)
                this.seen.delete(key);
    }
    begin(scope, command) {
        this.sweep();
        // Never let a second in-flight request replace the correlation of the first.
        if ([...this.pending.values()].some((value) => value.session === scope.session) ||
            this.pending.size + this.permits.size >= MAX_STATE || this.seen.size >= MAX_STATE ||
            this.seen.has(`${scope.session}\0${scope.call}`)) {
            this.clear(scope.session);
            throw new Error("authorization_conflict");
        }
        this.clear(scope.session);
        const nonce = randomBytes(32).toString("hex");
        const pending = { ...scope, nonce, command: command(nonce), until: this.now() + PENDING_MS };
        this.seen.set(`${scope.session}\0${scope.call}`, pending.until + PERMIT_MS);
        this.pending.set(scope.session, pending);
        return pending;
    }
    finish(scope, command, exit, output, verifyAuditor = () => { }) {
        this.sweep();
        const pending = this.pending.get(scope.session);
        this.clear(scope.session);
        if (!pending)
            return false;
        try {
            if (pending.call !== scope.call || pending.root !== scope.root ||
                pending.fingerprint !== scope.fingerprint || pending.command !== command || exit !== 0)
                return false;
            const frame = parseFrame(output, pending);
            verifyAuditor(frame);
            this.permits.set(scope.session, { ...pending, auditorRoot: frame.auditorRoot, auditorFingerprint: frame.auditorFingerprint, until: this.now() + PERMIT_MS });
            return true;
        }
        catch {
            return false;
        }
    }
    consume(scope) {
        this.sweep();
        const permit = this.permits.get(scope.session);
        this.clear(scope.session);
        if (!permit || permit.root !== scope.root || permit.fingerprint !== scope.fingerprint ||
            permit.call === scope.call || this.seen.has(`${scope.session}\0${scope.call}`)) {
            throw new Error("authorization_required");
        }
        this.seen.set(`${scope.session}\0${scope.call}`, this.now() + PENDING_MS + PERMIT_MS);
        return permit;
    }
}
