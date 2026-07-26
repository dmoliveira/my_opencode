import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readFileSync, readlinkSync, } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { TextDecoder } from "node:util";
const FINGERPRINT_VERSION = "git-state-v1";
const EVIDENCE_RELATIVE_PATH = ".opencode/runtime/validation-evidence.json";
const MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024;
const MAX_UNTRACKED_FILES = 2_048;
const MAX_UNTRACKED_FILE_BYTES = 4 * 1024 * 1024;
const MAX_UNTRACKED_TOTAL_BYTES = 16 * 1024 * 1024;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true });
function gitBytes(cwd, args) {
    return execFileSync("git", args, {
        cwd,
        stdio: ["ignore", "pipe", "ignore"],
        maxBuffer: MAX_GIT_OUTPUT_BYTES,
    });
}
function sha256(value) {
    return createHash("sha256").update(value).digest("hex");
}
function frame(hash, label, value) {
    const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value, "utf-8");
    hash.update(label, "utf-8");
    hash.update("\0", "utf-8");
    hash.update(String(bytes.length), "utf-8");
    hash.update("\0", "utf-8");
    hash.update(bytes);
}
function splitNul(value) {
    const entries = [];
    let start = 0;
    for (let index = 0; index < value.length; index += 1) {
        if (value[index] !== 0) {
            continue;
        }
        if (index > start) {
            entries.push(value.subarray(start, index));
        }
        start = index + 1;
    }
    if (start < value.length) {
        entries.push(value.subarray(start));
    }
    return entries;
}
function decodeGitPath(value) {
    const decoded = UTF8_DECODER.decode(value);
    if (!Buffer.from(decoded, "utf-8").equals(value)) {
        throw new Error("git path is not canonical UTF-8");
    }
    return decoded;
}
function resolveContainedPath(root, pathValue) {
    if (!pathValue || isAbsolute(pathValue) || pathValue.split(/[\\/]/).includes("..")) {
        throw new Error("git path is outside the worktree");
    }
    const absolute = resolve(root, pathValue);
    const scoped = relative(root, absolute);
    if (!scoped || scoped === ".." || scoped.startsWith(`..${sep}`) || isAbsolute(scoped)) {
        throw new Error("git path is outside the worktree");
    }
    return absolute;
}
function readRegularFileNoFollow(path, expectedSize) {
    if (expectedSize > MAX_UNTRACKED_FILE_BYTES) {
        throw new Error("untracked file exceeds fingerprint budget");
    }
    const flags = constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0);
    const descriptor = openSync(path, flags);
    try {
        const opened = fstatSync(descriptor);
        if (!opened.isFile() || opened.size !== expectedSize) {
            throw new Error("untracked file changed during fingerprinting");
        }
        const content = readFileSync(descriptor);
        if (content.length !== expectedSize) {
            throw new Error("untracked file changed during fingerprinting");
        }
        return content;
    }
    finally {
        closeSync(descriptor);
    }
}
function untrackedStateDigest(root, trackedDiff) {
    const untracked = splitNul(gitBytes(root, ["ls-files", "--others", "--exclude-standard", "-z"]))
        .filter((entry) => !entry.equals(Buffer.from(EVIDENCE_RELATIVE_PATH, "utf-8")))
        .sort(Buffer.compare);
    if (untracked.length > MAX_UNTRACKED_FILES) {
        throw new Error("untracked file count exceeds fingerprint budget");
    }
    const hash = createHash("sha256");
    frame(hash, "tracked", trackedDiff);
    let totalBytes = 0;
    for (const pathBytes of untracked) {
        const relativePath = decodeGitPath(pathBytes);
        const absolutePath = resolveContainedPath(root, relativePath);
        const state = lstatSync(absolutePath);
        let kind;
        let content;
        if (state.isSymbolicLink()) {
            kind = "symlink";
            content = readlinkSync(absolutePath, { encoding: "buffer" });
        }
        else if (state.isFile()) {
            kind = "file";
            content = readRegularFileNoFollow(absolutePath, state.size);
        }
        else {
            throw new Error("unsupported untracked file type");
        }
        totalBytes += content.length;
        if (content.length > MAX_UNTRACKED_FILE_BYTES ||
            totalBytes > MAX_UNTRACKED_TOTAL_BYTES) {
            throw new Error("untracked content exceeds fingerprint budget");
        }
        frame(hash, "path", pathBytes);
        frame(hash, "type", kind);
        frame(hash, "executable", state.mode & 0o111 ? "1" : "0");
        frame(hash, "size", String(content.length));
        frame(hash, "content-sha256", sha256(content));
    }
    return hash.digest("hex");
}
export function captureGitStateFingerprint(directory) {
    const cwd = directory.trim();
    if (!cwd) {
        return null;
    }
    try {
        const root = gitBytes(cwd, ["rev-parse", "--show-toplevel"])
            .toString("utf-8")
            .trim();
        const head = gitBytes(root, ["rev-parse", "--verify", "HEAD"])
            .toString("utf-8")
            .trim()
            .toLowerCase();
        if (!root || !/^[a-f0-9]{40,64}$/.test(head)) {
            return null;
        }
        const stagedDiff = gitBytes(root, [
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "HEAD",
            "--",
            ".",
            ":(exclude).opencode/runtime/validation-evidence.json",
        ]);
        const trackedDiff = gitBytes(root, [
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
            ".",
            ":(exclude).opencode/runtime/validation-evidence.json",
        ]);
        const index = sha256(stagedDiff);
        const worktree = untrackedStateDigest(root, trackedDiff);
        const digestHash = createHash("sha256");
        frame(digestHash, "version", FINGERPRINT_VERSION);
        frame(digestHash, "root", root);
        frame(digestHash, "head", head);
        frame(digestHash, "index", index);
        frame(digestHash, "worktree", worktree);
        return {
            version: FINGERPRINT_VERSION,
            root,
            head,
            index,
            worktree,
            digest: digestHash.digest("hex"),
        };
    }
    catch {
        return null;
    }
}
export function sameGitState(left, right) {
    return Boolean(left &&
        right &&
        left.version === FINGERPRINT_VERSION &&
        right.version === FINGERPRINT_VERSION &&
        left.digest === right.digest);
}
