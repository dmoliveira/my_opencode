import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { constants, closeSync, fchmodSync, fstatSync, lstatSync, mkdirSync, openSync, readSync, readdirSync, realpathSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
export const RUNNER = realpathSync(fileURLToPath(new URL("./runner.js", import.meta.url)));
const LIMIT = 4 * 1024 * 1024;
export const ENV = Object.freeze({
    PATH: "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", LANG: "C.UTF-8", LC_ALL: "C.UTF-8",
    UV_PYTHON_DOWNLOADS: "never", PYTHONDONTWRITEBYTECODE: "1",
});
export function digest(value) {
    return createHash("sha256").update(value).digest("hex");
}
const modules = ["index.js", "protocol.js", "capability.js", "runner.js", "safety.js"].map((name) => join(dirname(RUNNER), name));
const loadedIdentity = modules.map((path) => digest(safeRead(path)));
/** Reject aliases, hardlinks, special files and symlink ancestors before opening. */
export function safeRead(path, limit = LIMIT) {
    if (resolve(path) !== path || realpathSync(path) !== path)
        throw new Error("unsafe_path");
    const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
        const stat = fstatSync(fd);
        if (!stat.isFile() || stat.nlink !== 1 || stat.size > limit)
            throw new Error("unsafe_file");
        const buffer = Buffer.alloc(stat.size + 1);
        let size = 0;
        while (size < buffer.length) {
            const count = readSync(fd, buffer, size, buffer.length - size, size);
            if (!count)
                break;
            size += count;
        }
        const data = buffer.subarray(0, size);
        const after = fstatSync(fd);
        if (data.length > limit || after.size !== stat.size || after.mtimeMs !== stat.mtimeMs ||
            after.ctimeMs !== stat.ctimeMs || after.nlink !== 1)
            throw new Error("input_changed");
        return data;
    }
    finally {
        closeSync(fd);
    }
}
export function exists(path) {
    try {
        lstatSync(path);
        return true;
    }
    catch (error) {
        if (error.code === "ENOENT")
            return false;
        throw error;
    }
}
export function run(executable, args, cwd, timeout = 30_000, environment = {}) {
    return execFileSync(executable, args, {
        cwd, env: { ...ENV, ...environment }, timeout, maxBuffer: LIMIT, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
    });
}
function executable(name) {
    for (const dir of ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]) {
        const candidate = join(dir, name);
        if (!exists(candidate))
            continue;
        const path = realpathSync(candidate);
        safeRead(path, 128 * 1024 * 1024);
        return path;
    }
    throw new Error("trusted_executable_missing");
}
const INPUTS = ["pyproject.toml", "uv.lock", ".python-version"];
const EXECUTABLES = ["node", "git", "uv", "python"];
const DIRECTORIES = ["root", "cache", "git"];
const POLICY = "virtual-wheel-only-v3";
export const METADATA_POLICY = "read-only-editable-dot-metadata-v1";
const SHA256 = /^[a-f0-9]{64}$/;
function exactKeys(value, keys) {
    if (!value || typeof value !== "object" || Array.isArray(value) ||
        Object.keys(value).sort().join(",") !== [...keys].sort().join(","))
        throw new Error("snapshot_invalid");
}
function validPath(value) {
    if (typeof value !== "string" || value.length > 4096 || !value.startsWith("/") ||
        value.includes("\0") || resolve(value) !== value)
        throw new Error("snapshot_path_invalid");
}
function validDirectory(value) {
    exactKeys(value, ["path", "dev", "ino"]);
    validPath(value.path);
    if (![value.dev, value.ino].every((x) => typeof x === "string" && /^(?:0|[1-9][0-9]{0,39})$/.test(x)))
        throw new Error("snapshot_invalid");
}
function validFile(value) {
    exactKeys(value, ["path", "sha256"]);
    validPath(value.path);
    if (typeof value.sha256 !== "string" || !SHA256.test(value.sha256))
        throw new Error("snapshot_invalid");
}
function validateSnapshot(value) {
    exactKeys(value, ["v", "policy", "root", "fingerprint", "node", "git", "uv", "python", "cache", "version", "inputs", "executables", "helpers", "directories", "marker", "absent"]);
    const s = value;
    if (s.v !== 1 || ![POLICY, METADATA_POLICY].includes(s.policy) || typeof s.version !== "string" || !/^3\.(?:1[1-4])\.\d{1,3}$/.test(s.version) ||
        typeof s.fingerprint !== "string" || !SHA256.test(s.fingerprint) ||
        JSON.stringify(s.absent) !== '["uv.toml"]')
        throw new Error("snapshot_invalid");
    validPath(s.root);
    validPath(s.cache);
    exactKeys(s.inputs, INPUTS);
    for (const name of INPUTS)
        if (typeof s.inputs[name] !== "string" || !SHA256.test(s.inputs[name]))
            throw new Error("snapshot_invalid");
    exactKeys(s.executables, EXECUTABLES);
    for (const name of EXECUTABLES) {
        validFile(s.executables[name]);
        if (s[name] !== s.executables[name].path)
            throw new Error("snapshot_invalid");
    }
    if (!Array.isArray(s.helpers) || s.helpers.length !== modules.length)
        throw new Error("snapshot_invalid");
    s.helpers.forEach((file, i) => { validFile(file); if (file.path !== modules[i])
        throw new Error("snapshot_invalid"); });
    exactKeys(s.directories, DIRECTORIES);
    for (const name of DIRECTORIES)
        validDirectory(s.directories[name]);
    if (s.directories.root.path !== s.root || s.directories.cache.path !== s.cache)
        throw new Error("snapshot_invalid");
    exactKeys(s.marker, ["path", "dev", "ino", "kind", "sha256"]);
    validDirectory({ path: s.marker.path, dev: s.marker.dev, ino: s.marker.ino });
    if (s.marker.path !== join(s.root, ".git") || !["file", "directory"].includes(s.marker.kind) ||
        typeof s.marker.sha256 !== "string" || (s.marker.kind === "file" ? !SHA256.test(s.marker.sha256) : s.marker.sha256 !== ""))
        throw new Error("snapshot_invalid");
    if (snapshotFingerprint(s) !== s.fingerprint)
        throw new Error("snapshot_fingerprint_invalid");
}
/** Fixed tuple order, never arbitrary caller-controlled object ordering. */
export function snapshotFingerprint(s) {
    return digest(JSON.stringify([s.v, s.policy, s.root, s.node, s.git, s.uv, s.python, s.cache, s.version,
        INPUTS.map((name) => [name, s.inputs[name]]),
        EXECUTABLES.map((name) => [name, s.executables[name].path, s.executables[name].sha256]),
        s.helpers.map((file) => [file.path, file.sha256]),
        DIRECTORIES.map((name) => [name, s.directories[name].path, s.directories[name].dev, s.directories[name].ino]),
        [s.marker.path, s.marker.kind, s.marker.dev, s.marker.ino, s.marker.sha256], s.absent]));
}
function canonical(value) {
    if (Array.isArray(value))
        return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object")
        return "{" + Object.keys(value).sort()
            .map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
    return JSON.stringify(value);
}
export function encodeSnapshot(snapshot) {
    validateSnapshot(snapshot);
    const text = canonical(snapshot);
    if (Buffer.byteLength(text) > 24_576)
        throw new Error("snapshot_limit");
    return Buffer.from(text).toString("base64url");
}
export function decodeSnapshot(encoded) {
    if (!/^[A-Za-z0-9_-]{1,32768}$/.test(encoded))
        throw new Error("snapshot_invalid");
    const text = Buffer.from(encoded, "base64url").toString("utf8");
    if (Buffer.from(text).toString("base64url") !== encoded)
        throw new Error("snapshot_invalid");
    const value = JSON.parse(text);
    validateSnapshot(value);
    if (canonical(value) !== text)
        throw new Error("snapshot_noncanonical");
    return value;
}
export function directoryIdentity(path) {
    validPath(path);
    if (realpathSync(path) !== path)
        throw new Error("unsafe_directory");
    const stat = lstatSync(path, { bigint: true });
    if (!stat.isDirectory())
        throw new Error("unsafe_directory");
    return { path, dev: stat.dev.toString(), ino: stat.ino.toString() };
}
function markerIdentity(root) {
    const path = join(root, ".git");
    if (realpathSync(path) !== path)
        throw new Error("unsafe_git_marker");
    const stat = lstatSync(path, { bigint: true });
    if (!stat.isFile() && !stat.isDirectory())
        throw new Error("unsafe_git_marker");
    return { path, dev: stat.dev.toString(), ino: stat.ino.toString(), kind: stat.isFile() ? "file" : "directory",
        sha256: stat.isFile() ? digest(safeRead(path)) : "" };
}
function fileIdentity(path) {
    return { path, sha256: digest(safeRead(path, 128 * 1024 * 1024)) };
}
function verifyFile(file) {
    if (fileIdentity(file.path).sha256 !== file.sha256)
        throw new Error("bound_file_changed");
}
/** Pure continuity check: never execute Git, UV, Python, Node or scanner code. */
export function recapture(snapshot) {
    validateSnapshot(snapshot);
    for (const name of DIRECTORIES)
        if (canonical(directoryIdentity(snapshot.directories[name].path)) !== canonical(snapshot.directories[name]))
            throw new Error("directory_changed");
    if (canonical(markerIdentity(snapshot.root)) !== canonical(snapshot.marker))
        throw new Error("git_marker_changed");
    for (const name of snapshot.absent)
        if (exists(join(snapshot.root, name)))
            throw new Error("config_changed");
    for (const name of INPUTS)
        if (digest(safeRead(join(snapshot.root, name))) !== snapshot.inputs[name])
            throw new Error("input_changed");
    for (const name of EXECUTABLES)
        verifyFile(snapshot.executables[name]);
    snapshot.helpers.forEach((file, index) => {
        if (file.sha256 !== loadedIdentity[index])
            throw new Error("runner_changed");
        verifyFile(file);
    });
    return snapshot;
}
// No site initialization, .pth processing, user imports, project execution, or Python download.
const INSPECT = `import sys,json,tomllib\np=tomllib.loads(sys.argv[1])\nl=tomllib.loads(sys.argv[2])\nprint(json.dumps(dict(project=p,lock=l,version='.'.join(map(str,sys.version_info[:3])))))`;
export function validateProject(project, lock) {
    // Build-system support is deliberately refused: an empty build closure is provable.
    if ("build-system" in project || "dynamic" in (project.project ?? {}))
        throw new Error("build_backend_unsupported");
    const tool = (project.tool ?? {});
    const uv = (tool.uv ?? {});
    if (uv.package !== false || Object.keys(uv).some((key) => !["package", "default-groups"].includes(key))) {
        throw new Error("project_config_unsupported");
    }
    const groups = uv["default-groups"];
    if (groups !== undefined && JSON.stringify(groups) !== '["dev"]') {
        throw new Error("groups_unsupported");
    }
    const packages = lock.package;
    if (!Array.isArray(packages) || packages.length < 1 || packages.length > 512)
        throw new Error("lock_unsupported");
    let roots = 0;
    for (const pkg of packages) {
        const source = pkg.source;
        if (!source || typeof source !== "object")
            throw new Error("source_unsupported");
        if (JSON.stringify(source) === '{"virtual":"."}') {
            roots++;
            continue;
        }
        if (Object.keys(source).length !== 1 || source.registry !== "https://pypi.org/simple" ||
            !Array.isArray(pkg.wheels) || pkg.wheels.length === 0)
            throw new Error("source_unsupported");
        for (const wheel of pkg.wheels) {
            if (typeof wheel.url !== "string" || !wheel.url.startsWith("https://files.pythonhosted.org/") ||
                !/^[^?#]+\.whl$/.test(wheel.url) || !/^sha256:[a-f0-9]{64}$/.test(wheel.hash))
                throw new Error("wheel_unsupported");
        }
    }
    if (roots !== 1)
        throw new Error("workspace_unsupported");
}
/** Informational policy only: never accepted by audit/setup or scanner discovery. */
export function validateMetadataProject(project, lock) {
    const manifest = project.project;
    if (!manifest || typeof manifest.name !== "string" || typeof manifest.version !== "string" ||
        !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(manifest.name) || !manifest.version ||
        Object.keys(project).some((key) => !["project", "tool", "dependency-groups"].includes(key)) ||
        Object.keys((project.tool ?? {})).some((key) => key !== "uv") ||
        Object.keys(manifest).some((key) => !["name", "version", "requires-python", "dependencies", "description"].includes(key)) ||
        Object.keys((project["dependency-groups"] ?? {})).some((key) => key !== "dev"))
        throw new Error("metadata_manifest_unsupported");
    const dependencies = [manifest.dependencies ?? [], (project["dependency-groups"] ?? {}).dev ?? []];
    for (const group of dependencies)
        if (!Array.isArray(group) || group.some((item) => typeof item !== "string" ||
            !/^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?\s*(?:[<>=!~][A-Za-z0-9.*+!,<>=~ -]+)?$/.test(item)))
            throw new Error("metadata_dependency_unsupported");
    const packages = lock.package;
    if (!Array.isArray(packages))
        throw new Error("lock_unsupported");
    const roots = packages.filter((pkg) => canonical(pkg.source) === '{"editable":"."}');
    if (roots.length !== 1 || roots[0].name !== manifest.name || roots[0].version !== manifest.version ||
        new Set(packages.map((pkg) => canonical([pkg.name, pkg.version, pkg.source]))).size !== packages.length)
        throw new Error("metadata_root_unsupported");
    const virtual = packages.map((pkg) => pkg === roots[0] ? { ...pkg, source: { virtual: "." } } : pkg);
    validateProject(project, { ...lock, package: virtual });
}
/** Conservative byte edit; trusted TOML proof is separately required before UV runs. */
export function metadataCandidate(original) {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(original);
    if (!Buffer.from(text).equals(original))
        throw new Error("metadata_utf8_invalid");
    const matches = [...text.matchAll(/^source = \{ (editable) = "\." \}[^\S\r\n]*(?:#[^\r\n]*)?\r?$/gm)];
    if (matches.length !== 1)
        throw new Error("metadata_span_unsupported");
    const match = matches[0];
    const start = Buffer.byteLength(text.slice(0, match.index + 'source = { '.length));
    const end = start + Buffer.byteLength("editable");
    return { candidate: Buffer.concat([original.subarray(0, start), Buffer.from("virtual"), original.subarray(end)]), start, end };
}
/** Both strict parsed documents must agree outside the single matching root source. */
export function proveMetadataConversion(project, original, candidate, lock, converted) {
    const expected = metadataCandidate(original);
    if (!candidate.equals(expected.candidate))
        throw new Error("metadata_bytes_changed");
    validateMetadataProject(project, lock);
    const packages = lock.package;
    const mapped = packages.map((pkg) => canonical(pkg.source) === '{"editable":"."}' ? { ...pkg, source: { virtual: "." } } : pkg);
    if (canonical({ ...lock, package: mapped }) !== canonical(converted))
        throw new Error("metadata_semantics_changed");
    validateProject(project, converted);
}
/** Hash installed scanner code too, not merely its launcher/version string. */
function libraryDigest(paths) {
    const entries = [];
    let bytes = 0;
    let visited = 0;
    function visit(path) {
        if (++visited > 20_000)
            throw new Error("scanner_library_limit");
        const stat = lstatSync(path);
        if (stat.isDirectory()) {
            if (realpathSync(path) !== path)
                throw new Error("unsafe_library");
            for (const name of readdirSync(path).sort()) {
                visit(join(path, name));
            }
        }
        else {
            const data = safeRead(path, 16 * 1024 * 1024);
            bytes += data.length;
            if (bytes > 128 * 1024 * 1024 || entries.length >= 16_384)
                throw new Error("scanner_library_limit");
            entries.push(`${path}:${digest(data)}`);
        }
    }
    for (const path of paths)
        visit(path);
    return digest(entries.join("\n"));
}
export function capture(directory) {
    return capturePolicy(directory, POLICY);
}
export function captureMetadata(directory) {
    return capturePolicy(directory, METADATA_POLICY);
}
/** Identity plus bytes; timestamps deliberately are not authority fields. */
export function metadataFile(path) {
    const before = lstatSync(path, { bigint: true });
    const data = safeRead(path);
    const after = lstatSync(path, { bigint: true });
    if (!before.isFile() || before.nlink !== 1n || before.dev !== after.dev || before.ino !== after.ino ||
        before.uid !== after.uid || before.mode !== after.mode || before.size !== after.size ||
        before.ctimeNs !== after.ctimeNs || before.mtimeNs !== after.mtimeNs ||
        typeof process.getuid !== "function" || before.uid !== BigInt(process.getuid()) ||
        (Number(before.mode) & 0o7333) !== 0o200 || data.length !== Number(before.size))
        throw new Error("metadata_file_unsafe");
    return { path, dev: before.dev.toString(), ino: before.ino.toString(), uid: before.uid.toString(),
        mode: Number(before.mode) & 0o7777, size: data.length, sha256: digest(data) };
}
function validMetadataFile(file) {
    exactKeys(file, ["path", "dev", "ino", "uid", "mode", "size", "sha256"]);
    validDirectory({ path: file.path, dev: file.dev, ino: file.ino });
    validFile({ path: file.path, sha256: file.sha256 });
    if (typeof file.uid !== "string" || !/^(?:0|[1-9][0-9]{0,39})$/.test(file.uid) ||
        !Number.isSafeInteger(file.mode) || file.mode < 0 || file.mode > 0o777 || (file.mode & 0o333) !== 0o200 ||
        !Number.isSafeInteger(file.size) || file.size < 0 || file.size > LIMIT)
        throw new Error("metadata_file_invalid");
}
function metadataPointer(git) {
    const path = join(git, "commondir");
    if (!exists(path))
        return { kind: "absent" };
    const file = metadataFile(path);
    const bytes = safeRead(path);
    if (digest(bytes) !== file.sha256)
        throw new Error("metadata_pointer_changed");
    const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    // Git removes one final LF only. Spaces, including final spaces, are path bytes.
    const value = raw.endsWith("\n") ? raw.slice(0, -1) : raw;
    if (!value || /[\u0000-\u001f\u007f]/.test(value))
        throw new Error("metadata_pointer_invalid");
    const target = realpathSync(resolve(git, value));
    directoryIdentity(target);
    return { kind: "file", file, target };
}
export function metadataFingerprint(context) {
    const tuple = (f) => [f.path, f.dev, f.ino, f.uid, f.mode, f.size, f.sha256];
    return digest(JSON.stringify([context.v, context.policy, context.snapshot.fingerprint, tuple(context.original),
        [context.common.path, context.common.dev, context.common.ino], context.pointer.kind === "absent" ? ["absent"] :
            ["file", tuple(context.pointer.file), context.pointer.target]]));
}
function validateMetadataContext(value) {
    exactKeys(value, ["v", "policy", "snapshot", "original", "common", "pointer", "fingerprint"]);
    const c = value;
    validateSnapshot(c.snapshot);
    validMetadataFile(c.original);
    validDirectory(c.common);
    if (c.pointer?.kind === "absent")
        exactKeys(c.pointer, ["kind"]);
    else if (c.pointer?.kind === "file") {
        exactKeys(c.pointer, ["kind", "file", "target"]);
        validMetadataFile(c.pointer.file);
        validPath(c.pointer.target);
        if (c.pointer.file.path !== join(c.snapshot.directories.git.path, "commondir") || c.pointer.target !== c.common.path)
            throw new Error("metadata_context_invalid");
    }
    else
        throw new Error("metadata_context_invalid");
    if (c.v !== 1 || c.policy !== "one-key-metadata-promotion-v1" || c.snapshot.policy !== METADATA_POLICY ||
        c.original.path !== join(c.snapshot.root, "uv.lock") || c.original.sha256 !== c.snapshot.inputs["uv.lock"] ||
        (c.pointer.kind === "absent" && c.common.path !== c.snapshot.directories.git.path) ||
        c.fingerprint !== metadataFingerprint(c))
        throw new Error("metadata_context_invalid");
}
export function encodeMetadataContext(context) {
    validateMetadataContext(context);
    const text = canonical(context);
    if (Buffer.byteLength(text) > 32_768)
        throw new Error("metadata_context_limit");
    return Buffer.from(text).toString("base64url");
}
export function decodeMetadataContext(encoded) {
    if (!/^[A-Za-z0-9_-]{1,43691}$/.test(encoded))
        throw new Error("metadata_context_invalid");
    const text = Buffer.from(encoded, "base64url").toString("utf8");
    if (Buffer.from(text).toString("base64url") !== encoded)
        throw new Error("metadata_context_invalid");
    const value = JSON.parse(text);
    validateMetadataContext(value);
    if (canonical(value) !== text)
        throw new Error("metadata_context_noncanonical");
    return value;
}
export function captureMetadataContext(directory) {
    const snapshot = captureMetadata(directory);
    // Only bootstrap executes Git, after verifying the bound executable and all inputs.
    recapture(snapshot);
    const output = run(snapshot.git, ["-C", snapshot.root, "rev-parse", "--path-format=absolute", "--git-common-dir"], snapshot.root);
    const path = output.endsWith("\n") ? output.slice(0, -1) : output;
    if (/[\u0000-\u001f\u007f]/.test(path))
        throw new Error("metadata_common_invalid");
    const common = directoryIdentity(realpathSync(path));
    const value = { v: 1, policy: "one-key-metadata-promotion-v1", snapshot,
        original: metadataFile(join(snapshot.root, "uv.lock")), common, pointer: metadataPointer(snapshot.directories.git.path) };
    return recaptureMetadataContext({ ...value, fingerprint: metadataFingerprint(value) });
}
function metadataNonLock(context) {
    if (canonical(directoryIdentity(context.common.path)) !== canonical(context.common) ||
        canonical(metadataPointer(context.snapshot.directories.git.path)) !== canonical(context.pointer))
        throw new Error("metadata_git_changed");
    const target = context.pointer.kind === "file" ? context.pointer.target : context.snapshot.directories.git.path;
    if (target !== context.common.path)
        throw new Error("metadata_common_invalid");
}
export function recaptureMetadataContext(context) {
    validateMetadataContext(context);
    recapture(context.snapshot);
    metadataNonLock(context);
    if (canonical(metadataFile(context.original.path)) !== canonical(context.original))
        throw new Error("metadata_original_changed");
    return context;
}
/** The sole permitted post-state: this prepared inode, not identical replacement bytes. */
export function verifyMetadataTransition(context, prepared, candidateHash) {
    validateMetadataContext(context);
    validMetadataFile(prepared);
    if (!SHA256.test(candidateHash) || prepared.sha256 !== candidateHash || candidateHash === context.original.sha256 ||
        prepared.uid !== context.original.uid || prepared.mode !== context.original.mode || prepared.dev !== context.original.dev ||
        prepared.ino === context.original.ino || prepared.size !== context.original.size - 1)
        throw new Error("metadata_transition_invalid");
    metadataNonLock(context);
    const snapshot = { ...context.snapshot, inputs: { ...context.snapshot.inputs, "uv.lock": candidateHash } };
    snapshot.fingerprint = snapshotFingerprint(snapshot);
    recapture(snapshot);
    if (canonical(metadataFile(context.original.path)) !== canonical({ ...prepared, path: context.original.path }))
        throw new Error("metadata_transition_invalid");
}
export function metadataPaths(context, nonce) {
    validateMetadataContext(context);
    if (!SHA256.test(nonce))
        throw new Error("metadata_nonce_invalid");
    const namespace = join(context.common.path, "dependency-metadata-backups");
    const job = join(namespace, nonce);
    return { namespace, job, backup: join(job, "original.lock"), candidate: join(context.snapshot.root, `.dependency-metadata-${nonce}.candidate`) };
}
function privateDirectory(path) {
    const proof = directoryIdentity(path), stat = lstatSync(path);
    if (typeof process.getuid !== "function" || stat.uid !== process.getuid() || (stat.mode & 0o7777) !== 0o700)
        throw new Error("metadata_private_directory_invalid");
    return proof;
}
function retainFile(file) {
    const fd = openSync(file.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
        const st = fstatSync(fd, { bigint: true });
        if (!st.isFile() || st.dev.toString() !== file.dev || st.ino.toString() !== file.ino || st.nlink !== 1n ||
            st.uid.toString() !== file.uid || Number(st.size) !== file.size || (Number(st.mode) & 0o7777) !== file.mode)
            throw new Error("metadata_prepared_changed");
        return fd;
    }
    catch (error) {
        closeSync(fd);
        throw error;
    }
}
/** Called independently by the helper and live host callback, with no caller paths. */
export function inspectMetadataPreparation(context, nonce, candidateHash) {
    recaptureMetadataContext(context);
    const paths = metadataPaths(context, nonce);
    const namespace = privateDirectory(paths.namespace), job = privateDirectory(paths.job);
    const backup = metadataFile(paths.backup), candidate = metadataFile(paths.candidate);
    if (backup.mode !== 0o600 || backup.sha256 !== context.original.sha256 || backup.size !== context.original.size ||
        candidate.sha256 !== candidateHash || candidateHash === context.original.sha256 || !SHA256.test(candidateHash) ||
        candidate.mode !== context.original.mode || candidate.uid !== context.original.uid || candidate.dev !== context.original.dev ||
        candidate.ino === context.original.ino || candidate.size !== context.original.size - 1)
        throw new Error("metadata_preparation_invalid");
    const descriptors = [];
    try {
        descriptors.push(retainFile(backup));
        descriptors.push(retainFile(candidate));
        return { namespace, job, backup, candidate, descriptors };
    }
    catch (error) {
        for (const fd of descriptors)
            closeSync(fd);
        throw error;
    }
}
export function verifyMetadataPreparation(context, nonce, candidateHash, prepared) {
    const actual = inspectMetadataPreparation(context, nonce, candidateHash);
    try {
        for (const key of ["namespace", "job", "backup", "candidate"]) {
            if (canonical(actual[key]) !== canonical(prepared[key]))
                throw new Error("metadata_prepared_changed");
        }
    }
    finally {
        closeMetadataPreparation(actual);
    }
}
export function closeMetadataPreparation(prepared, cleanup = false) {
    // No source path is ever a cleanup target. Completed and incomplete backup jobs stay.
    if (cleanup) {
        try {
            if (canonical(metadataFile(prepared.candidate.path)) === canonical(prepared.candidate))
                unlinkSync(prepared.candidate.path);
        }
        catch { /* replaced/absent files are never removed */ }
    }
    for (const fd of prepared.descriptors.splice(0))
        closeSync(fd);
}
export function verifyMetadataRecovery(prepared) {
    if (canonical(privateDirectory(prepared.namespace.path)) !== canonical(prepared.namespace) ||
        canonical(privateDirectory(prepared.job.path)) !== canonical(prepared.job) ||
        canonical(metadataFile(prepared.backup.path)) !== canonical(prepared.backup))
        throw new Error("metadata_recovery_changed");
}
export function prepareMetadata(context, nonce, expected) {
    recaptureMetadataContext(context);
    const paths = metadataPaths(context, nonce);
    const common = lstatSync(context.common.path);
    if (typeof process.getuid !== "function" || common.uid !== process.getuid() || (common.mode & 0o022))
        throw new Error("metadata_common_unsafe");
    if (!exists(paths.namespace))
        mkdirSync(paths.namespace, { mode: 0o700 });
    privateDirectory(paths.namespace);
    mkdirSync(paths.job, { mode: 0o700 }); // Exclusive job; collision is never reused or deleted.
    privateDirectory(paths.job);
    const original = safeRead(context.original.path), candidate = metadataCandidate(original).candidate;
    if (digest(original) !== context.original.sha256 || digest(candidate) !== expected)
        throw new Error("metadata_candidate_mismatch");
    writeFileSync(paths.backup, original, { mode: 0o600, flag: "wx" });
    let fd;
    try {
        fd = openSync(paths.candidate, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
        writeFileSync(fd, candidate);
        fchmodSync(fd, context.original.mode);
        return inspectMetadataPreparation(context, nonce, expected);
    }
    catch (error) {
        if (fd !== undefined) {
            try {
                const owned = fstatSync(fd, { bigint: true }), actual = lstatSync(paths.candidate, { bigint: true });
                if (actual.isFile() && actual.dev === owned.dev && actual.ino === owned.ino && actual.nlink === 1n)
                    unlinkSync(paths.candidate);
            }
            catch { /* retain replacements */ }
        }
        throw error;
    }
    finally {
        if (fd !== undefined)
            closeSync(fd);
    }
}
function capturePolicy(directory, policy) {
    const root = resolve(directory);
    if (realpathSync(root) !== root || !lstatSync(root).isDirectory())
        throw new Error("unsafe_worktree");
    if (modules.some((path, index) => digest(safeRead(path)) !== loadedIdentity[index]))
        throw new Error("runner_changed");
    // Bootstrap assumes a trusted host baseline; hash each tool before its first use.
    const gitFile = fileIdentity(executable("git"));
    const bootstrap = (file, args) => { verifyFile(file); return run(file.path, args, root); };
    const gitRoot = bootstrap(gitFile, ["-C", root, "rev-parse", "--show-toplevel"]).trim();
    if (gitRoot !== root)
        throw new Error("worktree_root_required");
    if (exists(join(root, "uv.toml")))
        throw new Error("config_unsupported");
    const inputs = INPUTS.map((name) => safeRead(join(root, name)));
    const files = inputs.map((data) => digest(data));
    const inputHashes = Object.fromEntries(INPUTS.map((name, i) => [name, files[i]]));
    const node = executable("node");
    const uv = executable("uv");
    const uvFile = fileIdentity(uv);
    const nodeFile = fileIdentity(node);
    if (!bootstrap(uvFile, ["--version"]).startsWith("uv 0.13.6 "))
        throw new Error("uv_version_unsupported");
    const cache = realpathSync(bootstrap(uvFile, ["cache", "dir", "--no-config"]).trim());
    const pin = inputs[2].toString().trim();
    if (!/^3\.(?:1[1-4])\.\d{1,3}$/.test(pin))
        throw new Error("interpreter_unsupported");
    // Find only an already installed interpreter; UV cannot download or import the project.
    const found = bootstrap(uvFile, ["python", "find", "--offline", "--no-project", "--no-config", "--no-python-downloads", pin]).trim();
    if (!found.startsWith("/") || found.startsWith(root + "/"))
        throw new Error("interpreter_unsupported");
    const python = realpathSync(found);
    const pythonFile = fileIdentity(python);
    const inspected = JSON.parse(bootstrap(pythonFile, ["-I", "-S", "-B", "-c", INSPECT, inputs[0].toString(), inputs[1].toString()]));
    if (inputs[2].toString().trim() !== inspected.version)
        throw new Error("interpreter_unsupported");
    if (policy === METADATA_POLICY)
        validateMetadataProject(inspected.project, inspected.lock);
    else
        validateProject(inspected.project, inspected.lock);
    const gitDirectory = realpathSync(bootstrap(gitFile, ["-C", root, "rev-parse", "--absolute-git-dir"]).trim());
    const bound = {
        v: 1, policy, root, node, git: gitFile.path, uv, python, cache, version: inspected.version, inputs: inputHashes,
        executables: { node: nodeFile, git: gitFile, uv: uvFile, python: pythonFile },
        helpers: modules.map((path, i) => ({ path, sha256: loadedIdentity[i] })),
        directories: { root: directoryIdentity(root), cache: directoryIdentity(cache), git: directoryIdentity(gitDirectory) },
        marker: markerIdentity(root), absent: ["uv.toml"],
    };
    return recapture({ ...bound, fingerprint: snapshotFingerprint(bound) });
}
/** Non-executing verification: changed auditor code must not run before rejection. */
export function captureAuditor(root, snapshot) {
    if (snapshot.policy === METADATA_POLICY)
        throw new Error("metadata_snapshot_not_authorized");
    const cache = snapshot.cache;
    if (resolve(cache) !== cache || realpathSync(cache) !== cache)
        throw new Error("auditor_path_invalid");
    if (resolve(root) !== root || realpathSync(root) !== root || !root.startsWith(cache + "/archive-v0/") ||
        dirname(root) !== join(cache, "archive-v0"))
        throw new Error("auditor_path_invalid");
    const python = realpathSync(join(root, "bin", "python"));
    if (python !== snapshot.python)
        throw new Error("auditor_interpreter_mismatch");
    const libraries = [join(root, "lib", "python" + snapshot.version.split(".").slice(0, 2).join("."), "site-packages")];
    const fingerprint = digest(JSON.stringify({ root, python, interpreter: digest(safeRead(python, 128 * 1024 * 1024)),
        config: digest(safeRead(join(root, "pyvenv.cfg"))), libraries: libraryDigest(libraries) }));
    return { root, python, libraries, fingerprint };
}
/** Only the normal Bash runner calls this; offline fixed-tool discovery has no project inputs. */
export function discoverAuditor(snapshot, subprocess = run) {
    if (snapshot.policy === METADATA_POLICY)
        throw new Error("metadata_snapshot_not_authorized");
    recapture(snapshot);
    const output = subprocess(snapshot.uv, ["tool", "run", "--offline", "--no-config", "--no-python-downloads", "--no-env-file", "--no-build",
        "--python", snapshot.python, "--from", "pip-audit==2.10.1", "python", "-I", "-S", "-B", "-c", "import sys;print(sys.executable)"], "/", 60_000).trim();
    if (!output.startsWith("/") || output.includes("\n") || !output.endsWith("/bin/python"))
        throw new Error("auditor_discovery_invalid");
    return captureAuditor(realpathSync(dirname(dirname(output))), snapshot);
}
export function quote(value) { return "'" + value.replace(/'/g, "'\\''") + "'"; }
export function runnerCommand(snapshot, mode, nonce, socket = "", auditorRoot = "", auditorFingerprint = "") {
    if (snapshot.policy === METADATA_POLICY)
        throw new Error("metadata_snapshot_not_authorized");
    return [snapshot.node, RUNNER, mode, snapshot.root, nonce, snapshot.fingerprint, socket, auditorRoot, auditorFingerprint, encodeSnapshot(snapshot)].map(quote).join(" ");
}
