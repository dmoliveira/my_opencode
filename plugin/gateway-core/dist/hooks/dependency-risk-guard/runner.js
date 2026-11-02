import { mkdtempSync, mkdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { connect } from "node:net";
import { fileURLToPath } from "node:url";
import { recapture, captureAuditor, discoverAuditor, decodeSnapshot, directoryIdentity, digest, exists, run, safeRead } from "./safety.js";
const normalize = (name) => name.toLowerCase().replace(/[-_.]+/g, "-");
/** No URLs, includes, arbitrary options or extras. Markers require trusted host evaluation. */
export function requirements(text, evaluate, collecting = false) {
    if (Buffer.byteLength(text) > 4 * 1024 * 1024)
        throw new Error("requirements_limit");
    const result = [];
    for (const line of text.replace(/\\\r?\n\s*/g, " ").split(/\r?\n/)) {
        if (!line.trim())
            continue;
        const match = /^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)(?:\s*;\s*(.+?))?\s+((?:--hash=sha256:[a-f0-9]{64}\s*)+)$/.exec(line.trim());
        if (!match)
            throw new Error("requirements_unsupported");
        if (match[3]) {
            if (!evaluate)
                throw new Error("marker_evaluation_required");
            const applicable = evaluate(match[3]);
            if (typeof applicable !== "boolean")
                throw new Error("marker_invalid");
            if (!applicable)
                continue;
        }
        const name = normalize(match[1]);
        if (!collecting && result.some((item) => item.name === name))
            throw new Error("requirements_duplicate");
        result.push({ name, version: match[2], hashes: [...match[4].matchAll(/sha256:([a-f0-9]{64})/g)].map((m) => m[1]).sort() });
    }
    if (result.length < 1 || result.length > 512)
        throw new Error("requirements_limit");
    return result.sort((a, b) => a.name.localeCompare(b.name));
}
export function hostRequirements(text, snapshot, auditor, subprocess) {
    const markers = [];
    // Parse once to collect validated marker strings, then evaluate in one bounded subprocess.
    requirements(text, (marker) => { markers.push(marker); return true; }, true);
    if (!markers.length)
        return requirements(text);
    const script = "import sys,json;sys.path.extend(" + JSON.stringify(auditor.libraries) + ");from packaging.markers import Marker;print(json.dumps([Marker(m).evaluate() for m in json.loads(sys.argv[1])]))";
    const values = JSON.parse(subprocess(snapshot.python, ["-I", "-S", "-B", "-c", script, JSON.stringify(markers)], snapshot.root));
    if (!Array.isArray(values) || values.length !== markers.length || !values.every((x) => typeof x === "boolean"))
        throw new Error("marker_invalid");
    let i = 0;
    return requirements(text, () => values[i++]);
}
function serializeRequirements(items) {
    return items.map((x) => `${x.name}==${x.version} ${x.hashes.map((h) => `--hash=sha256:${h}`).join(" ")}`).join("\n") + "\n";
}
function packageSet(items) {
    return items.map((x) => `${normalize(x.name)}==${x.version}`).sort().join("\n");
}
export function samePackages(actual, expected) {
    if (!Array.isArray(actual) || actual.length !== expected.length ||
        !actual.every((x) => x && typeof x.name === "string" && typeof x.version === "string") ||
        new Set(actual.map((x) => normalize(x.name))).size !== actual.length ||
        packageSet(actual) !== packageSet(expected))
        throw new Error("package_coverage_invalid");
}
export function validateAudit(text, expected) {
    if (Buffer.byteLength(text) > 4 * 1024 * 1024)
        throw new Error("audit_limit");
    const value = JSON.parse(text);
    const compact = text.replace(/"(?:\\.|[^"\\])*"|\s+/g, (token) => token.startsWith('"') ? token : "");
    if (JSON.stringify(value) !== compact)
        throw new Error("audit_noncanonical");
    if (!value || Object.keys(value).sort().join(",") !== "dependencies,fixes" ||
        !Array.isArray(value.fixes) || value.fixes.length !== 0 || !Array.isArray(value.dependencies))
        throw new Error("audit_invalid");
    samePackages(value.dependencies, expected);
    for (const item of value.dependencies) {
        if (Object.keys(item).sort().join(",") !== "name,version,vulns" || !Array.isArray(item.vulns) || item.vulns.length !== 0) {
            throw new Error("audit_incomplete_or_vulnerable");
        }
    }
}
function unchanged(snapshot, inspect) {
    if (inspect(snapshot).fingerprint !== snapshot.fingerprint)
        throw new Error("input_changed");
}
// -S suppresses executable .pth/sitecustomize; only the hashed scanner libraries are added.
function scanner(auditor, args, cwd, subprocess) {
    const script = "import sys,runpy;sys.path.extend(" + JSON.stringify(auditor.libraries) + ");sys.argv=['pip-audit']+sys.argv[1:];runpy.run_module('pip_audit',run_name='__main__')";
    return subprocess(auditor.python, ["-I", "-S", "-B", "-c", script, ...args], cwd, 60_000);
}
async function redeem(socket, nonce, fingerprint) {
    if (!socket.startsWith(join(realpathSync(tmpdir()), "dependency-authority-")))
        throw new Error("capability_invalid");
    await new Promise((resolve, reject) => {
        const client = connect(socket);
        let result = "";
        client.setTimeout(5000, () => client.destroy(new Error("capability_timeout")));
        client.on("error", reject);
        client.on("connect", () => client.end(JSON.stringify({ nonce, fingerprint }) + "\n"));
        client.on("data", (chunk) => { result += chunk.toString(); if (result.length > 16)
            client.destroy(new Error("capability_invalid")); });
        client.on("end", () => result === "authorized\n" ? resolve() : reject(new Error("capability_invalid")));
    });
}
/** Every setup repeats the real audit; no receipt or supplied package list is accepted. */
export async function execute(mode, root, nonce, fingerprint, socket, auditorRoot = "", auditorFingerprint = "", boundSnapshot = undefined, boundary = {
    inspect: recapture, subprocess: run, auditor: discoverAuditor, inspectAuditor: captureAuditor,
}) {
    // The CLI accepts eight strings, never this unit-fixture subprocess boundary.
    const { inspect } = boundary;
    if (!["audit", "setup"].includes(mode) || !/^[a-f0-9]{64}$/.test(nonce) || !/^[a-f0-9]{64}$/.test(fingerprint) ||
        (mode === "audit" && (socket !== "" || auditorRoot !== "" || auditorFingerprint !== "")) ||
        (mode === "setup" && (!socket || !auditorRoot || !/^[a-f0-9]{64}$/.test(auditorFingerprint))) ||
        !boundSnapshot || boundSnapshot.root !== root || boundSnapshot.fingerprint !== fingerprint)
        throw new Error("invocation_invalid");
    const snapshot = inspect(boundSnapshot);
    if (snapshot.fingerprint !== fingerprint || exists(join(root, ".venv")))
        throw new Error("input_changed_or_environment_exists");
    let boundAuditor;
    let environmentBinding;
    const recheck = () => {
        unchanged(snapshot, inspect);
        if (boundAuditor && boundary.inspectAuditor(boundAuditor.root, snapshot).fingerprint !== boundAuditor.fingerprint)
            throw new Error("auditor_changed");
        if (environmentBinding) {
            const actual = directoryIdentity(environmentBinding.path);
            if (actual.dev !== environmentBinding.dev || actual.ino !== environmentBinding.ino)
                throw new Error("environment_changed");
        }
        else if (exists(join(root, ".venv")))
            throw new Error("environment_exists");
    };
    // Every subprocess shares the same non-executing preflight, including discovery.
    const subprocess = (...args) => { recheck(); return boundary.subprocess(...args); };
    // Setup never rediscovers or executes a granted scanner before hashing it.
    const auditor = mode === "setup" ? boundary.inspectAuditor(auditorRoot, snapshot) : boundary.auditor(snapshot, subprocess);
    if (mode === "setup" && (auditor.root !== auditorRoot || auditor.fingerprint !== auditorFingerprint))
        throw new Error("auditor_changed");
    boundAuditor = auditor;
    const temporary = realpathSync(mkdtempSync(join(tmpdir(), "dependency-audit-")));
    try {
        // Immutable copies avoid transient edits between validation and UV parsing. This is
        // equivalent only for virtual projects with registry-only dependencies: no local build.
        for (const name of ["pyproject.toml", "uv.lock", ".python-version"]) {
            const input = safeRead(join(root, name));
            if (digest(input) !== snapshot.inputs[name])
                throw new Error("input_changed");
            writeFileSync(join(temporary, name), input, { mode: 0o600, flag: "wx" });
        }
        recheck();
        const base = ["--no-config", "--no-cache", "--no-python-downloads", "--color", "never"];
        const exported = subprocess(snapshot.uv, ["export", ...base, "--locked", "--no-header", "--no-annotate", "--no-emit-project", "--no-build"], temporary);
        const locked = hostRequirements(exported, snapshot, auditor, subprocess);
        const hostLocked = serializeRequirements(locked);
        const input = join(temporary, "closure.in");
        const output = join(temporary, "closure.txt");
        writeFileSync(input, hostLocked, { mode: 0o600, flag: "wx" });
        subprocess(snapshot.uv, ["pip", "compile", ...base, input, "--python", snapshot.python,
            "--only-binary", ":all:", "--generate-hashes", "--no-header", "--no-annotate", "--output-file", output], temporary, 60_000);
        const compiled = hostRequirements(safeRead(output).toString(), snapshot, auditor, subprocess);
        samePackages(compiled, locked);
        for (const item of compiled) {
            if (!item.hashes.some((hash) => locked.find((x) => x.name === item.name).hashes.includes(hash)))
                throw new Error("locked_hash_coverage_invalid");
        }
        // Compilation proves the wheel closure, but must never expand the lock's allowed hashes.
        const closure = locked;
        writeFileSync(output, hostLocked, { mode: 0o600 });
        recheck();
        if (scanner(auditor, ["--version"], temporary, subprocess).trim() !== "pip-audit 2.10.1")
            throw new Error("auditor_version_invalid");
        const report = scanner(auditor, ["--strict", "--disable-pip", "--no-deps", "--require-hashes", "-r", output,
            "--format", "json", "--progress-spinner", "off"], temporary, subprocess);
        validateAudit(report, closure);
        recheck();
        const frame = { v: 1, nonce, fingerprint, packages: closure.length,
            closure: digest(JSON.stringify(closure)), auditor: "pip-audit==2.10.1", operation: "uv-sync-locked", build: "none",
            auditorRoot: auditor.root, auditorFingerprint: auditor.fingerprint };
        if (mode === "setup") {
            await redeem(socket, nonce, digest(fingerprint + auditor.fingerprint));
            recheck();
            if (exists(join(root, ".venv")))
                throw new Error("environment_exists");
            const environment = join(root, ".venv");
            mkdirSync(environment, { mode: 0o700 });
            environmentBinding = directoryIdentity(environment);
            subprocess(snapshot.uv, ["venv", ...base, "--allow-existing", "--python", snapshot.python, environment], temporary);
            const python = join(environment, process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
            // The wheels are the entire external closure; no sdist or build-isolation resolution.
            subprocess(snapshot.uv, ["pip", "sync", ...base, "--python", python, "--require-hashes", "--only-binary", ":all:", "--link-mode", "copy", "--strict", output], temporary, 60_000);
            recheck();
            subprocess(snapshot.uv, ["sync", ...base, "--locked", "--no-build-isolation", "--inexact", "--no-build", "--link-mode", "copy", "--python", snapshot.python], temporary, 60_000, { UV_PROJECT_ENVIRONMENT: environment });
            const installed = JSON.parse(subprocess(snapshot.uv, ["pip", "list", ...base, "--python", python, "--format", "json"], temporary));
            samePackages(installed, closure);
            recheck();
        }
        return frame;
    }
    finally {
        rmSync(temporary, { recursive: true, force: true });
    }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
    // No exception text or subprocess output: those may contain private paths/inventories.
    const timer = setTimeout(() => process.exit(1), 150_000);
    const args = process.argv.slice(2);
    const result = Promise.resolve().then(() => {
        if (args.length !== 8)
            throw new Error("invocation_invalid");
        return execute(...args.slice(0, 7), decodeSnapshot(args[7]));
    });
    result
        .then((frame) => { clearTimeout(timer); process.stdout.write(JSON.stringify(frame) + "\n"); })
        .catch(() => { clearTimeout(timer); process.stderr.write("dependency_security_refused\n"); process.exitCode = 1; });
}
