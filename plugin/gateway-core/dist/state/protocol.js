import { randomBytes } from "node:crypto";
import { closeSync, constants as fsConstants, fchmodSync, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, readSync, realpathSync, renameSync, rmdirSync, unlinkSync, writeSync, } from "node:fs";
import { dirname, join } from "node:path";
export const STATE_RELATIVE_PATH = ".opencode/gateway-core.state.json";
export const STATE_DIRECTORY_NAME = ".opencode";
export const STATE_FILE_NAME = "gateway-core.state.json";
export const LOCK_DIRECTORY_NAME = "gateway-core.state.json.lock";
export const OWNER_TOKEN_NAME = "owner-token";
export const STAGE_PREFIX = ".gateway-core.state.json.stage-";
export const LOCK_TIMEOUT_MS = 2000;
export const LOCK_POLL_MS = 20;
export const MAX_STATE_BYTES = 4 * 1024 * 1024;
export const PRIVATE_DIRECTORY_MODE = 0o700;
export const PRIVATE_FILE_MODE = 0o600;
export const TOKEN_RANDOM_BYTES = 32;
export const TOKEN_TEXT_BYTES = 65;
export const JSON_INDENT = 2;
export const MAX_SAFE_INTEGER = 9_007_199_254_740_991;
export const LOCK_RECOVERY_GUIDANCE = "stop the gateway state owner, then manually remove the lock directory";
const SUPPORTED_PLATFORMS = new Set(["darwin", "linux"]);
const O_CLOEXEC = fsConstants.O_CLOEXEC ?? 0;
const TOKEN_PATTERN = /^[0-9a-f]{64}\n$/;
const ROOT_UPDATE_KEYS = new Set(["lastUpdatedAt", "source"]);
const DOMAIN_KEYS = {
    activeLoop: new Set([
        "active",
        "sessionId",
        "objective",
        "doneCriteria",
        "ignoredCompletionCycles",
        "completionMode",
        "completionPromise",
        "iteration",
        "maxIterations",
        "startedAt",
    ]),
    conciseMode: new Set(["mode", "source", "sessionId", "activatedAt", "updatedAt"]),
    executionStatus: new Set(["version", "sessions"]),
};
const ACTIVE_LOCKS = new Set();
const SLEEP_ARRAY = new Int32Array(new SharedArrayBuffer(4));
const FATAL_UTF8 = new TextDecoder("utf-8", { fatal: true });
export class GatewayStateProtocolError extends Error {
    reasonCode;
    phase;
    committed;
    durability;
    lockReleased;
    causeCode;
    secondaryReasonCode;
    constructor(reasonCode, message, options) {
        super(message);
        this.name = "GatewayStateProtocolError";
        this.reasonCode = reasonCode;
        this.phase = options.phase;
        this.committed = options.committed ?? false;
        this.durability = options.durability ?? "not_committed";
        this.lockReleased = options.lockReleased ?? false;
        this.causeCode = causeCode(options.cause);
        this.secondaryReasonCode = options.secondaryReasonCode ?? null;
    }
    toJSON() {
        return {
            reason_code: this.reasonCode,
            message: this.message,
            phase: this.phase,
            committed: this.committed,
            durability: this.durability,
            lock_released: this.lockReleased,
            cause_code: this.causeCode,
            secondary_reason_code: this.secondaryReasonCode,
        };
    }
}
function causeCode(cause) {
    if (!cause || typeof cause !== "object") {
        return cause ? String(cause) : null;
    }
    const code = cause.code;
    return code ? String(code) : cause.constructor?.name ?? null;
}
function protocolError(reasonCode, message, phase, cause) {
    return new GatewayStateProtocolError(reasonCode, message, { phase, cause });
}
function isErrno(error, code) {
    return Boolean(error && typeof error === "object" && error.code === code);
}
function pathLexists(path) {
    try {
        lstatSync(path);
        return true;
    }
    catch {
        return false;
    }
}
function requireSupportedPlatform() {
    if (!SUPPORTED_PLATFORMS.has(process.platform)) {
        throw protocolError("gateway_state_unsupported_platform", "gateway state persistence supports only Darwin and Linux", "preflight");
    }
}
function currentUid() {
    const getter = process.geteuid;
    if (typeof getter !== "function") {
        throw protocolError("gateway_state_unsupported_platform", "gateway state persistence requires effective UID support", "preflight");
    }
    return getter();
}
function directoryFlags() {
    return fsConstants.O_RDONLY | fsConstants.O_DIRECTORY | fsConstants.O_NOFOLLOW | O_CLOEXEC;
}
function fileReadFlags() {
    return fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW | fsConstants.O_NONBLOCK | O_CLOEXEC;
}
function lstatExact(path) {
    return lstatSync(path, { bigint: true });
}
function fstatExact(descriptor) {
    return fstatSync(descriptor, { bigint: true });
}
function identity(stats) {
    return {
        dev: stats.dev,
        ino: stats.ino,
        mode: stats.mode,
        nlink: stats.nlink,
        uid: stats.uid,
        size: stats.size,
        mtimeNs: stats.mtimeNs,
        ctimeNs: stats.ctimeNs,
    };
}
function sameObject(left, right) {
    return left.dev === right.dev && left.ino === right.ino;
}
function sameSnapshot(left, right) {
    return (sameObject(left, right) &&
        left.mode === right.mode &&
        left.nlink === right.nlink &&
        left.uid === right.uid &&
        left.size === right.size &&
        left.mtimeNs === right.mtimeNs &&
        left.ctimeNs === right.ctimeNs);
}
function sameReadSnapshot(left, right) {
    return (sameObject(left, right) &&
        left.mode === right.mode &&
        left.uid === right.uid &&
        left.size === right.size &&
        left.mtimeNs === right.mtimeNs);
}
function validateDirectory(stats, reasonCode, label) {
    if (!stats.isDirectory() || stats.uid !== BigInt(currentUid()) || (stats.mode & 18n) !== 0n) {
        throw protocolError(reasonCode, `${label} must be current-user-owned and not group/world writable`, "authority");
    }
}
function validateAncestorNamespace(root) {
    let child = root;
    while (true) {
        const parent = dirname(child);
        if (parent === child) {
            return;
        }
        let parentStats;
        let childStats;
        try {
            parentStats = lstatExact(parent);
            childStats = lstatExact(child);
        }
        catch (error) {
            throw protocolError("gateway_state_unsafe_project_root", "gateway state ancestor namespace is unavailable", "authority", error);
        }
        if (!parentStats.isDirectory() || !childStats.isDirectory()) {
            throw protocolError("gateway_state_unsafe_project_root", "gateway state ancestor namespace contains a non-directory", "authority");
        }
        const trustedParentOwner = parentStats.uid === BigInt(currentUid()) || parentStats.uid === 0n;
        if (!trustedParentOwner) {
            throw protocolError("gateway_state_unsafe_project_root", "gateway state ancestor namespace has a foreign owner", "authority");
        }
        if ((parentStats.mode & 18n) !== 0n) {
            const sticky = (parentStats.mode & 512n) !== 0n;
            const protectedChild = childStats.uid === BigInt(currentUid()) || childStats.uid === 0n;
            if (!sticky || !protectedChild) {
                throw protocolError("gateway_state_unsafe_project_root", "gateway state ancestor namespace permits unsafe rename", "authority");
            }
        }
        child = parent;
    }
}
function openVerifiedDirectory(path, reasonCode, label) {
    let before;
    let descriptor = -1;
    try {
        before = lstatExact(path);
        validateDirectory(before, reasonCode, label);
        descriptor = openSync(path, directoryFlags());
        const opened = fstatExact(descriptor);
        if (!sameObject(identity(before), identity(opened))) {
            throw protocolError(reasonCode, `${label} changed while opening`, "authority");
        }
        validateDirectory(opened, reasonCode, label);
        return [descriptor, identity(opened)];
    }
    catch (error) {
        if (descriptor >= 0) {
            closeSync(descriptor);
        }
        if (error instanceof GatewayStateProtocolError) {
            throw error;
        }
        throw protocolError(reasonCode, `unable to open ${label}`, "authority", error);
    }
}
function revalidatePath(path, expected, reasonCode, label) {
    let current;
    try {
        current = lstatExact(path);
    }
    catch (error) {
        throw protocolError(reasonCode, `${label} is unavailable`, "authority", error);
    }
    validateDirectory(current, reasonCode, label);
    if (!sameObject(identity(current), expected)) {
        throw protocolError(reasonCode, `${label} identity changed`, "authority");
    }
}
function withStateAuthority(directory, createDirectory, run) {
    requireSupportedPlatform();
    let root;
    try {
        root = realpathSync.native(directory);
    }
    catch (error) {
        throw protocolError("gateway_state_unsafe_project_root", "gateway state project root is unavailable", "authority", error);
    }
    validateAncestorNamespace(root);
    const [rootFd, rootIdentity] = openVerifiedDirectory(root, "gateway_state_unsafe_project_root", "gateway state project root");
    const stateDirectory = join(root, STATE_DIRECTORY_NAME);
    let directoryFd = null;
    try {
        let metadata;
        let created = false;
        try {
            metadata = lstatExact(stateDirectory);
        }
        catch (error) {
            if (!isErrno(error, "ENOENT")) {
                throw protocolError("gateway_state_unsafe_directory", "unable to inspect gateway state directory", "authority", error);
            }
            if (!createDirectory) {
                return run({
                    root,
                    directory: stateDirectory,
                    rootFd,
                    directoryFd: null,
                    rootIdentity,
                    directoryIdentity: null,
                });
            }
            revalidatePath(root, rootIdentity, "gateway_state_unsafe_project_root", "gateway state project root");
            try {
                mkdirSync(stateDirectory, { mode: PRIVATE_DIRECTORY_MODE });
                created = true;
            }
            catch (mkdirError) {
                if (!isErrno(mkdirError, "EEXIST")) {
                    throw protocolError("gateway_state_unsafe_directory", "unable to create gateway state directory", "authority", mkdirError);
                }
            }
            if (created) {
                try {
                    fsyncSync(rootFd);
                }
                catch (syncError) {
                    throw protocolError("gateway_state_io_failed", "gateway state directory creation durability failed", "authority", syncError);
                }
            }
            metadata = lstatExact(stateDirectory);
        }
        validateDirectory(metadata, "gateway_state_unsafe_directory", "gateway state directory");
        directoryFd = openSync(stateDirectory, directoryFlags());
        if (created) {
            fchmodSync(directoryFd, PRIVATE_DIRECTORY_MODE);
        }
        const opened = fstatExact(directoryFd);
        if (!sameObject(identity(metadata), identity(opened))) {
            throw protocolError("gateway_state_unsafe_directory", "gateway state directory changed while opening", "authority");
        }
        validateDirectory(opened, "gateway_state_unsafe_directory", "gateway state directory");
        const directoryIdentity = identity(opened);
        return run({ root, directory: stateDirectory, rootFd, directoryFd, rootIdentity, directoryIdentity });
    }
    finally {
        if (directoryFd !== null) {
            closeSync(directoryFd);
        }
        closeSync(rootFd);
    }
}
function revalidateAuthority(authority) {
    revalidatePath(authority.root, authority.rootIdentity, "gateway_state_unsafe_project_root", "gateway state project root");
    if (authority.directoryIdentity) {
        revalidatePath(authority.directory, authority.directoryIdentity, "gateway_state_unsafe_directory", "gateway state directory");
    }
}
function validateTarget(stats) {
    if (!stats.isFile() || stats.nlink !== 1n || stats.uid !== BigInt(currentUid())) {
        throw protocolError("gateway_state_unsafe_target", "gateway state target must be a current-user-owned single-link regular file", "read");
    }
}
function validateOpenedTarget(stats) {
    if (!stats.isFile() ||
        (stats.nlink !== 0n && stats.nlink !== 1n) ||
        stats.uid !== BigInt(currentUid())) {
        throw protocolError("gateway_state_unsafe_target", "opened gateway state must be a current-user-owned regular file", "read");
    }
}
function readBounded(descriptor, maximumBytes) {
    const chunks = [];
    let total = 0;
    while (total <= maximumBytes) {
        const chunk = Buffer.allocUnsafe(Math.min(64 * 1024, maximumBytes + 1 - total));
        const observed = readSync(descriptor, chunk, 0, chunk.length, null);
        if (observed === 0) {
            break;
        }
        chunks.push(chunk.subarray(0, observed));
        total += observed;
    }
    if (total > maximumBytes) {
        throw protocolError("gateway_state_too_large", "gateway state exceeds its byte limit", "read");
    }
    return Buffer.concat(chunks, total);
}
function isRecord(value) {
    return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
function setOwn(target, key, value) {
    Object.defineProperty(target, key, {
        value,
        enumerable: true,
        configurable: true,
        writable: true,
    });
}
function cloneJson(value) {
    if (value === undefined) {
        return undefined;
    }
    if (value === null || typeof value === "string" || typeof value === "boolean") {
        return value;
    }
    if (typeof value === "number") {
        if (!Number.isFinite(value) || (Number.isInteger(value) && Math.abs(value) > MAX_SAFE_INTEGER)) {
            throw protocolError("gateway_state_number_unsupported", "gateway state number exceeds the cross-runtime range", "parse");
        }
        return value;
    }
    if (Array.isArray(value)) {
        return value.map((item) => {
            if (item === undefined) {
                throw protocolError("gateway_state_malformed_json", "gateway state arrays cannot contain undefined values", "parse");
            }
            return cloneJson(item);
        });
    }
    if (isRecord(value)) {
        const cloned = Object.create(null);
        for (const key of Object.keys(value)) {
            const clonedValue = cloneJson(value[key]);
            if (clonedValue !== undefined) {
                setOwn(cloned, key, clonedValue);
            }
        }
        return cloned;
    }
    throw protocolError("gateway_state_malformed_json", "gateway state contains a non-JSON value", "parse");
}
function parseState(raw) {
    let text;
    try {
        text = FATAL_UTF8.decode(raw);
    }
    catch (error) {
        throw protocolError("gateway_state_invalid_utf8", "gateway state is not valid UTF-8", "parse", error);
    }
    let parsed;
    try {
        parsed = JSON.parse(text);
    }
    catch (error) {
        throw protocolError("gateway_state_malformed_json", "gateway state contains malformed JSON", "parse", error);
    }
    if (!isRecord(parsed)) {
        throw protocolError("gateway_state_root_not_object", "gateway state root must be a JSON object", "parse");
    }
    return cloneJson(parsed);
}
function readState(authority, options = {}) {
    if (authority.directoryFd === null) {
        return { state: Object.create(null), snapshot: null };
    }
    const path = join(authority.directory, STATE_FILE_NAME);
    let descriptor = -1;
    try {
        descriptor = openSync(path, fileReadFlags());
        options.failureInjector?.("after_state_open");
        const opened = fstatExact(descriptor);
        validateOpenedTarget(opened);
        const before = identity(opened);
        if (before.size > BigInt(MAX_STATE_BYTES)) {
            throw protocolError("gateway_state_too_large", "gateway state exceeds its byte limit", "read");
        }
        const raw = readBounded(descriptor, MAX_STATE_BYTES);
        const after = identity(fstatExact(descriptor));
        if (!sameReadSnapshot(before, after) || BigInt(raw.length) !== before.size) {
            throw protocolError("gateway_state_target_changed", "gateway state changed while reading", "read");
        }
        return { state: parseState(raw), snapshot: before };
    }
    catch (error) {
        if (isErrno(error, "ENOENT")) {
            return { state: Object.create(null), snapshot: null };
        }
        if (error instanceof GatewayStateProtocolError) {
            throw error;
        }
        throw protocolError("gateway_state_unsafe_target", "unable to open gateway state without following links", "read", error);
    }
    finally {
        if (descriptor >= 0) {
            closeSync(descriptor);
        }
    }
}
export function resolveStatePath(directory) {
    return join(directory, STATE_RELATIVE_PATH);
}
export function resolveLockPath(directory) {
    return join(directory, STATE_DIRECTORY_NAME, LOCK_DIRECTORY_NAME);
}
export function loadRawGatewayState(directory, options = {}) {
    return withStateAuthority(directory, false, (authority) => cloneJson(readState(authority, options).state));
}
export function loadRawGatewayStateSnapshot(directory, options = {}) {
    return withStateAuthority(directory, false, (authority) => {
        const result = readState(authority, options);
        return {
            state: cloneJson(result.state),
            exists: result.snapshot !== null,
        };
    });
}
function sleep(milliseconds) {
    if (milliseconds > 0) {
        Atomics.wait(SLEEP_ARRAY, 0, 0, milliseconds);
    }
}
function validateLockDirectory(stats) {
    if (!stats.isDirectory() ||
        stats.uid !== BigInt(currentUid()) ||
        (stats.mode & 511n) !== BigInt(PRIVATE_DIRECTORY_MODE)) {
        throw protocolError("gateway_state_lock_unsafe", "gateway state lock directory is unsafe", "lock_acquire");
    }
}
function namedLockGeneration(lockPath, expected) {
    try {
        return sameObject(identity(lstatExact(lockPath)), expected) ? "same" : "changed";
    }
    catch (error) {
        if (isErrno(error, "ENOENT")) {
            return "missing";
        }
        throw protocolError("gateway_state_lock_unsafe", "unable to confirm gateway state lock generation", "lock_acquire", error);
    }
}
function confirmTokenPathUnsafe(lockPath, expectedLock, error, failureInjector) {
    failureInjector?.("before_lock_token_unsafe_confirmation");
    // This detects normal pathname turnover; it is not strict same-UID ABA provenance.
    const generation = namedLockGeneration(lockPath, expectedLock);
    if (generation === "missing") {
        return "missing";
    }
    if (generation === "changed") {
        return "initializing";
    }
    throw error;
}
function inspectExistingLock(authority, failureInjector) {
    const lockPath = join(authority.directory, LOCK_DIRECTORY_NAME);
    let metadata;
    try {
        metadata = lstatExact(lockPath);
    }
    catch (error) {
        if (isErrno(error, "ENOENT")) {
            return "missing";
        }
        throw protocolError("gateway_state_lock_unsafe", "unable to inspect gateway state lock", "lock_acquire", error);
    }
    if (!metadata.isDirectory() ||
        metadata.uid !== BigInt(currentUid()) ||
        (metadata.mode & 63n) !== 0n) {
        throw protocolError("gateway_state_lock_unsafe", "gateway state lock directory is unsafe", "lock_acquire");
    }
    if ((metadata.mode & 511n) !== BigInt(PRIVATE_DIRECTORY_MODE)) {
        return "initializing";
    }
    let lockFd = -1;
    try {
        lockFd = openSync(lockPath, directoryFlags());
        const opened = fstatExact(lockFd);
        if (!sameObject(identity(metadata), identity(opened))) {
            return "initializing";
        }
        validateLockDirectory(opened);
        const tokenPath = join(lockPath, OWNER_TOKEN_NAME);
        let tokenMetadata;
        try {
            tokenMetadata = lstatExact(tokenPath);
        }
        catch (error) {
            if (isErrno(error, "ENOENT")) {
                return "initializing";
            }
            return confirmTokenPathUnsafe(lockPath, identity(metadata), protocolError("gateway_state_lock_unsafe", "unable to inspect gateway state lock token", "lock_acquire", error), failureInjector);
        }
        if (tokenMetadata.nlink === 0n) {
            return "initializing";
        }
        if (!tokenMetadata.isFile() ||
            tokenMetadata.uid !== BigInt(currentUid()) ||
            tokenMetadata.nlink > 1n ||
            (tokenMetadata.mode & 63n) !== 0n ||
            tokenMetadata.size > BigInt(TOKEN_TEXT_BYTES)) {
            return confirmTokenPathUnsafe(lockPath, identity(metadata), protocolError("gateway_state_lock_unsafe", "gateway state lock token is unsafe", "lock_acquire"), failureInjector);
        }
        if ((tokenMetadata.mode & 511n) !== BigInt(PRIVATE_FILE_MODE) ||
            tokenMetadata.size < BigInt(TOKEN_TEXT_BYTES)) {
            return "initializing";
        }
        let tokenFd = -1;
        let token;
        try {
            tokenFd = openSync(tokenPath, fileReadFlags());
            const openedToken = identity(fstatExact(tokenFd));
            if (!sameSnapshot(openedToken, identity(tokenMetadata))) {
                return "initializing";
            }
            token = readBounded(tokenFd, TOKEN_TEXT_BYTES);
            if (!sameSnapshot(identity(fstatExact(tokenFd)), identity(tokenMetadata))) {
                return "initializing";
            }
        }
        catch (error) {
            if (isErrno(error, "ENOENT")) {
                return "missing";
            }
            return confirmTokenPathUnsafe(lockPath, identity(metadata), error instanceof GatewayStateProtocolError
                ? error
                : protocolError("gateway_state_lock_unsafe", "unable to read gateway state lock token", "lock_acquire", error), failureInjector);
        }
        finally {
            if (tokenFd >= 0) {
                closeSync(tokenFd);
            }
        }
        const generation = namedLockGeneration(lockPath, identity(metadata));
        if (generation === "missing") {
            return "missing";
        }
        if (generation === "changed") {
            return "initializing";
        }
        let tokenText;
        try {
            tokenText = FATAL_UTF8.decode(token);
        }
        catch (error) {
            return confirmTokenPathUnsafe(lockPath, identity(metadata), protocolError("gateway_state_lock_unsafe", "gateway state lock token is not valid UTF-8", "lock_acquire", error), failureInjector);
        }
        if (!TOKEN_PATTERN.test(tokenText)) {
            return confirmTokenPathUnsafe(lockPath, identity(metadata), protocolError("gateway_state_lock_unsafe", "gateway state lock token is malformed", "lock_acquire"), failureInjector);
        }
        return "locked";
    }
    catch (error) {
        if (isErrno(error, "ENOENT")) {
            return "missing";
        }
        if (error instanceof GatewayStateProtocolError) {
            throw error;
        }
        throw protocolError("gateway_state_lock_unsafe", "gateway state lock changed during inspection", "lock_acquire", error);
    }
    finally {
        if (lockFd >= 0) {
            closeSync(lockFd);
        }
    }
}
function removePartialOwnedLock(authority, expected) {
    const lockPath = join(authority.directory, LOCK_DIRECTORY_NAME);
    try {
        const current = identity(lstatExact(lockPath));
        if (!sameObject(current, expected)) {
            return;
        }
        const tokenPath = join(lockPath, OWNER_TOKEN_NAME);
        try {
            unlinkSync(tokenPath);
        }
        catch (error) {
            if (!isErrno(error, "ENOENT")) {
                return;
            }
        }
        if (sameObject(identity(lstatExact(lockPath)), expected)) {
            rmdirSync(lockPath);
        }
    }
    catch {
        return;
    }
}
function acquireLock(authority, options) {
    if (authority.directoryFd === null) {
        throw protocolError("gateway_state_unsafe_directory", "gateway state directory is unavailable", "lock_acquire");
    }
    const lockPath = join(authority.directory, LOCK_DIRECTORY_NAME);
    if (ACTIVE_LOCKS.has(lockPath)) {
        throw protocolError("gateway_state_lock_reentrant", "gateway state transaction is not reentrant", "lock_acquire");
    }
    const timeoutMs = Math.max(0, options.timeoutMs ?? LOCK_TIMEOUT_MS);
    if (!Number.isFinite(timeoutMs)) {
        throw protocolError("gateway_state_invalid_timeout", "gateway state lock timeout must be a finite number", "lock_acquire");
    }
    const deadline = performance.now() + timeoutMs;
    while (true) {
        revalidateAuthority(authority);
        try {
            mkdirSync(lockPath, { mode: PRIVATE_DIRECTORY_MODE });
            break;
        }
        catch (error) {
            if (!isErrno(error, "EEXIST")) {
                throw protocolError("gateway_state_io_failed", "unable to create gateway state lock", "lock_acquire", error);
            }
            const state = inspectExistingLock(authority, options.failureInjector);
            if (performance.now() >= deadline) {
                throw protocolError("gateway_state_lock_timeout", "gateway state lock acquisition timed out", "lock_acquire");
            }
            if (state === "missing") {
                continue;
            }
            sleep(Math.min(LOCK_POLL_MS, Math.max(0, deadline - performance.now())));
        }
    }
    let lockFd = -1;
    let lockIdentity = null;
    try {
        lockFd = openSync(lockPath, directoryFlags());
        fchmodSync(lockFd, PRIVATE_DIRECTORY_MODE);
        const metadata = fstatExact(lockFd);
        validateLockDirectory(metadata);
        lockIdentity = identity(metadata);
        ACTIVE_LOCKS.add(lockPath);
        const token = Buffer.from(`${randomBytes(TOKEN_RANDOM_BYTES).toString("hex")}\n`, "ascii");
        const tokenPath = join(lockPath, OWNER_TOKEN_NAME);
        const tokenFd = openSync(tokenPath, fsConstants.O_WRONLY |
            fsConstants.O_CREAT |
            fsConstants.O_EXCL |
            fsConstants.O_NOFOLLOW |
            O_CLOEXEC, PRIVATE_FILE_MODE);
        try {
            fchmodSync(tokenFd, PRIVATE_FILE_MODE);
            writeAll(tokenFd, token);
            fsyncSync(tokenFd);
        }
        finally {
            closeSync(tokenFd);
        }
        fsyncSync(lockFd);
        options.failureInjector?.("after_lock_publish");
        revalidateAuthority(authority);
        const current = identity(lstatExact(lockPath));
        if (!sameObject(current, lockIdentity)) {
            throw protocolError("gateway_state_lock_unsafe", "gateway state lock changed during publication", "lock_acquire");
        }
        return { key: lockPath, token, dev: lockIdentity.dev, ino: lockIdentity.ino };
    }
    catch (error) {
        ACTIVE_LOCKS.delete(lockPath);
        if (lockIdentity) {
            removePartialOwnedLock(authority, lockIdentity);
        }
        if (error instanceof GatewayStateProtocolError) {
            throw error;
        }
        throw protocolError("gateway_state_io_failed", "unable to publish gateway state lock", "lock_acquire", error);
    }
    finally {
        if (lockFd >= 0) {
            closeSync(lockFd);
        }
    }
}
function releaseLock(authority, lock, failureInjector) {
    const lockPath = join(authority.directory, LOCK_DIRECTORY_NAME);
    let removed = false;
    try {
        revalidateAuthority(authority);
        const metadata = identity(lstatExact(lockPath));
        if (metadata.dev !== lock.dev || metadata.ino !== lock.ino) {
            throw protocolError("gateway_state_lock_release_failed", "gateway state lock identity changed before release", "lock_release");
        }
        const lockFd = openSync(lockPath, directoryFlags());
        try {
            const opened = identity(fstatExact(lockFd));
            if (opened.dev !== lock.dev || opened.ino !== lock.ino) {
                throw protocolError("gateway_state_lock_release_failed", "gateway state lock changed while opening for release", "lock_release");
            }
            const tokenPath = join(lockPath, OWNER_TOKEN_NAME);
            const tokenFd = openSync(tokenPath, fileReadFlags());
            let token;
            try {
                token = readBounded(tokenFd, TOKEN_TEXT_BYTES);
            }
            finally {
                closeSync(tokenFd);
            }
            if (!token.equals(lock.token)) {
                throw protocolError("gateway_state_lock_release_failed", "gateway state lock token changed before release", "lock_release");
            }
            unlinkSync(tokenPath);
        }
        finally {
            closeSync(lockFd);
        }
        const current = identity(lstatExact(lockPath));
        if (current.dev !== lock.dev || current.ino !== lock.ino) {
            throw protocolError("gateway_state_lock_release_failed", "gateway state lock identity changed during release", "lock_release");
        }
        rmdirSync(lockPath);
        removed = true;
        failureInjector?.("after_lock_remove");
        if (authority.directoryFd === null) {
            throw protocolError("gateway_state_lock_release_failed", "gateway state directory closed before lock release", "lock_release");
        }
        fsyncSync(authority.directoryFd);
    }
    catch (error) {
        if (error instanceof GatewayStateProtocolError) {
            error.lockReleased = removed || error.lockReleased;
            throw error;
        }
        throw new GatewayStateProtocolError("gateway_state_lock_release_failed", "unable to release gateway state lock", { phase: "lock_release", cause: error, lockReleased: removed });
    }
    finally {
        ACTIVE_LOCKS.delete(lock.key);
    }
}
function writeAll(descriptor, payload) {
    let offset = 0;
    while (offset < payload.length) {
        offset += writeSync(descriptor, payload, offset, payload.length - offset, null);
    }
}
function snapshotMatches(authority, expected) {
    const path = join(authority.directory, STATE_FILE_NAME);
    let metadata;
    try {
        metadata = lstatExact(path);
    }
    catch (error) {
        return isErrno(error, "ENOENT") && expected === null;
    }
    if (expected === null) {
        return false;
    }
    try {
        validateTarget(metadata);
    }
    catch {
        return false;
    }
    return sameSnapshot(identity(metadata), expected);
}
function serializeState(state) {
    const safe = cloneJson(state);
    let text;
    try {
        text = `${JSON.stringify(safe, null, JSON_INDENT)}\n`;
    }
    catch (error) {
        throw protocolError("gateway_state_number_unsupported", "gateway state cannot be represented safely across runtimes", "serialize", error);
    }
    const payload = Buffer.from(text, "utf8");
    if (payload.length > MAX_STATE_BYTES) {
        throw protocolError("gateway_state_too_large", "serialized gateway state exceeds its byte limit", "serialize");
    }
    return payload;
}
function removeOwnedStage(path, expected) {
    try {
        if (sameObject(identity(lstatExact(path)), expected)) {
            unlinkSync(path);
        }
    }
    catch {
        return;
    }
}
function commitState(authority, state, expected, options) {
    const payload = serializeState(state);
    const stagePath = join(authority.directory, `${STAGE_PREFIX}${randomBytes(16).toString("hex")}`);
    const statePath = join(authority.directory, STATE_FILE_NAME);
    let stageFd = -1;
    let stageIdentity = null;
    let committed = false;
    try {
        revalidateAuthority(authority);
        stageFd = openSync(stagePath, fsConstants.O_WRONLY |
            fsConstants.O_CREAT |
            fsConstants.O_EXCL |
            fsConstants.O_NOFOLLOW |
            O_CLOEXEC, PRIVATE_FILE_MODE);
        fchmodSync(stageFd, PRIVATE_FILE_MODE);
        const stageMetadata = fstatExact(stageFd);
        stageIdentity = identity(stageMetadata);
        if (!stageMetadata.isFile() ||
            stageMetadata.nlink !== 1n ||
            stageMetadata.uid !== BigInt(currentUid()) ||
            (stageMetadata.mode & 511n) !== BigInt(PRIVATE_FILE_MODE)) {
            throw protocolError("gateway_state_stage_unsafe", "gateway state stage file is unsafe", "stage");
        }
        writeAll(stageFd, payload);
        fsyncSync(stageFd);
        options.failureInjector?.("after_stage_fsync");
        closeSync(stageFd);
        stageFd = -1;
        revalidateAuthority(authority);
        if (!snapshotMatches(authority, expected)) {
            throw protocolError("gateway_state_target_changed", "gateway state changed before commit", "pre_replace");
        }
        renameSync(stagePath, statePath);
        committed = true;
        options.failureInjector?.("after_replace");
        if (authority.directoryFd === null) {
            throw new Error("state directory unavailable after replace");
        }
        fsyncSync(authority.directoryFd);
    }
    catch (error) {
        if (committed) {
            throw new GatewayStateProtocolError("committed_durability_uncertain", "gateway state was committed but directory durability is uncertain", {
                phase: "directory_sync",
                cause: error,
                committed: true,
                durability: "uncertain",
            });
        }
        if (error instanceof GatewayStateProtocolError) {
            throw error;
        }
        throw protocolError("gateway_state_io_failed", "gateway state commit failed before replacement", "stage", error);
    }
    finally {
        if (stageFd >= 0) {
            closeSync(stageFd);
        }
        if (!committed && stageIdentity) {
            removeOwnedStage(stagePath, stageIdentity);
        }
    }
}
function mergeDomain(domain, current, mutation) {
    const mode = mutation.mode ?? "replace";
    if (mode !== "replace" && mode !== "patch") {
        throw protocolError("gateway_state_invalid_domain_update", "gateway state mutation mode is invalid", "mutate");
    }
    if (mutation.value === null) {
        return null;
    }
    if (!isRecord(mutation.value)) {
        throw protocolError("gateway_state_invalid_domain_update", "gateway state domain update must be an object or null", "mutate");
    }
    const existing = isRecord(current) ? cloneJson(current) : Object.create(null);
    const merged = Object.create(null);
    if (mode === "patch") {
        for (const key of Object.keys(existing)) {
            setOwn(merged, key, existing[key]);
        }
    }
    else {
        for (const key of Object.keys(existing)) {
            if (!DOMAIN_KEYS[domain].has(key)) {
                setOwn(merged, key, existing[key]);
            }
        }
    }
    for (const key of Object.keys(mutation.value)) {
        setOwn(merged, key, cloneJson(mutation.value[key]));
    }
    return merged;
}
export function transactGatewayStateDomain(directory, domain, mutator, options = {}) {
    if (domain !== "activeLoop" && domain !== "conciseMode" && domain !== "executionStatus") {
        throw protocolError("gateway_state_invalid_domain_update", "gateway state transaction must select exactly one known domain", "mutate");
    }
    if (options.timeoutMs !== undefined && !Number.isFinite(options.timeoutMs)) {
        throw protocolError("gateway_state_invalid_timeout", "gateway state lock timeout must be a finite number", "lock_acquire");
    }
    return withStateAuthority(directory, true, (authority) => {
        let lock = null;
        let primaryError = null;
        let result = null;
        let releaseSucceeded = false;
        try {
            lock = acquireLock(authority, options);
            const { state, snapshot } = readState(authority, options);
            const mutation = mutator(cloneJson(state[domain]), cloneJson(state));
            if (mutation === null) {
                result = { state: cloneJson(state), changed: false, commit: null };
            }
            else {
                const rootUpdates = mutation.rootUpdates ?? {};
                if (Object.keys(rootUpdates).some((key) => !ROOT_UPDATE_KEYS.has(key))) {
                    throw protocolError("gateway_state_invalid_domain_update", "gateway state root update owns unsupported fields", "mutate");
                }
                const next = cloneJson(state);
                setOwn(next, domain, mergeDomain(domain, state[domain], mutation));
                for (const key of Object.keys(rootUpdates)) {
                    if (key === "source" && rootUpdates[key] === null) {
                        delete next[key];
                    }
                    else {
                        setOwn(next, key, cloneJson(rootUpdates[key]));
                    }
                }
                commitState(authority, next, snapshot, options);
                result = {
                    state: cloneJson(next),
                    changed: true,
                    commit: {
                        path: join(authority.directory, STATE_FILE_NAME),
                        committed: true,
                        durability: "synced",
                        lockReleased: false,
                    },
                };
            }
        }
        catch (error) {
            primaryError =
                error instanceof GatewayStateProtocolError
                    ? error
                    : protocolError("gateway_state_io_failed", "gateway state transaction failed", "transaction", error);
        }
        finally {
            if (lock) {
                try {
                    options.failureInjector?.("before_lock_release");
                    releaseLock(authority, lock, options.failureInjector);
                    releaseSucceeded = true;
                }
                catch (releaseError) {
                    ACTIVE_LOCKS.delete(lock.key);
                    const normalized = releaseError instanceof GatewayStateProtocolError
                        ? releaseError
                        : protocolError("gateway_state_lock_release_failed", "gateway state lock release failed", "lock_release", releaseError);
                    releaseSucceeded = normalized.lockReleased;
                    if (primaryError) {
                        primaryError.secondaryReasonCode = normalized.reasonCode;
                    }
                    else {
                        const committed = Boolean(result?.commit?.committed);
                        primaryError = new GatewayStateProtocolError(committed ? "committed_lock_release_failed" : "gateway_state_lock_release_failed", "gateway state lock release failed after transaction", {
                            phase: "lock_release",
                            committed,
                            durability: committed ? "synced" : "not_committed",
                            lockReleased: releaseSucceeded,
                            cause: normalized,
                        });
                    }
                }
            }
        }
        if (primaryError) {
            primaryError.lockReleased = releaseSucceeded;
            throw primaryError;
        }
        if (!result) {
            throw protocolError("gateway_state_io_failed", "gateway state transaction produced no result", "transaction");
        }
        if (result.commit) {
            result.commit.lockReleased = releaseSucceeded;
        }
        return result;
    });
}
export function updateGatewayStateDomain(directory, domain, value, mutationOptions = {}, transactionOptions = {}) {
    return transactGatewayStateDomain(directory, domain, () => ({
        value: cloneJson(value),
        mode: mutationOptions.mode ?? "replace",
        rootUpdates: mutationOptions.rootUpdates
            ? cloneJson(mutationOptions.rootUpdates)
            : undefined,
    }), transactionOptions);
}
export function gatewayStateLockStatus(directory) {
    const path = resolveLockPath(directory);
    try {
        return withStateAuthority(directory, false, (authority) => {
            if (authority.directoryFd === null) {
                return {
                    path,
                    present: false,
                    safe: true,
                    state: "missing",
                    recovery_guidance: LOCK_RECOVERY_GUIDANCE,
                };
            }
            const state = inspectExistingLock(authority);
            return {
                path,
                present: state !== "missing",
                safe: true,
                state,
                recovery_guidance: LOCK_RECOVERY_GUIDANCE,
            };
        });
    }
    catch (error) {
        const reasonCode = error instanceof GatewayStateProtocolError ? error.reasonCode : "gateway_state_io_failed";
        return {
            path,
            present: pathLexists(path),
            safe: false,
            state: "unsafe",
            reason_code: reasonCode,
            recovery_guidance: LOCK_RECOVERY_GUIDANCE,
        };
    }
}
