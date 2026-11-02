import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { constants, closeSync, fstatSync, lstatSync, openSync, readSync, readdirSync, realpathSync } from "node:fs";
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
    if (s.v !== 1 || s.policy !== POLICY || typeof s.version !== "string" || !/^3\.(?:1[1-4])\.\d{1,3}$/.test(s.version) ||
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
    validateProject(inspected.project, inspected.lock);
    const gitDirectory = realpathSync(bootstrap(gitFile, ["-C", root, "rev-parse", "--absolute-git-dir"]).trim());
    const bound = {
        v: 1, policy: POLICY, root, node, git: gitFile.path, uv, python, cache, version: inspected.version, inputs: inputHashes,
        executables: { node: nodeFile, git: gitFile, uv: uvFile, python: pythonFile },
        helpers: modules.map((path, i) => ({ path, sha256: loadedIdentity[i] })),
        directories: { root: directoryIdentity(root), cache: directoryIdentity(cache), git: directoryIdentity(gitDirectory) },
        marker: markerIdentity(root), absent: ["uv.toml"],
    };
    return recapture({ ...bound, fingerprint: snapshotFingerprint(bound) });
}
/** Non-executing verification: changed auditor code must not run before rejection. */
export function captureAuditor(root, snapshot) {
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
    recapture(snapshot);
    const output = subprocess(snapshot.uv, ["tool", "run", "--offline", "--no-config", "--no-python-downloads", "--no-env-file", "--no-build",
        "--python", snapshot.python, "--from", "pip-audit==2.10.1", "python", "-I", "-S", "-B", "-c", "import sys;print(sys.executable)"], "/", 60_000).trim();
    if (!output.startsWith("/") || output.includes("\n") || !output.endsWith("/bin/python"))
        throw new Error("auditor_discovery_invalid");
    return captureAuditor(realpathSync(dirname(dirname(output))), snapshot);
}
export function quote(value) { return "'" + value.replace(/'/g, "'\\''") + "'"; }
export function runnerCommand(snapshot, mode, nonce, socket = "", auditorRoot = "", auditorFingerprint = "") {
    return [snapshot.node, RUNNER, mode, snapshot.root, nonce, snapshot.fingerprint, socket, auditorRoot, auditorFingerprint, encodeSnapshot(snapshot)].map(quote).join(" ");
}
