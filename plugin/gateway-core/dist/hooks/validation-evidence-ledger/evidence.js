import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
const evidenceBySession = new Map();
const evidenceByWorktree = new Map();
// Returns blank evidence snapshot.
function emptyEvidence() {
    return {
        lint: false,
        test: false,
        typecheck: false,
        build: false,
        security: false,
        updatedAt: "",
    };
}
function evidenceFilePath(directory) {
    const cwd = directory.trim() || process.cwd();
    try {
        const root = execFileSync("git", ["rev-parse", "--show-toplevel"], {
            cwd,
            stdio: ["ignore", "pipe", "ignore"],
        })
            .toString("utf-8")
            .trim();
        return resolve(root || cwd, ".opencode", "runtime", "validation-evidence.json");
    }
    catch {
        return resolve(cwd, ".opencode", "runtime", "validation-evidence.json");
    }
}
function readPersistedEvidence(directory) {
    try {
        const payload = JSON.parse(readFileSync(evidenceFilePath(directory), "utf-8"));
        return {
            sessions: payload && typeof payload.sessions === "object" ? payload.sessions : {},
            worktrees: payload && typeof payload.worktrees === "object" ? payload.worktrees : {},
        };
    }
    catch {
        return { sessions: {}, worktrees: {} };
    }
}
function writePersistedEvidence(directory) {
    const filePath = evidenceFilePath(directory);
    const persisted = readPersistedEvidence(directory);
    const sessions = {
        ...persisted.sessions,
        ...Object.fromEntries(evidenceBySession.entries()),
    };
    const worktrees = {
        ...persisted.worktrees,
        ...Object.fromEntries(evidenceByWorktree.entries()),
    };
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, JSON.stringify({ sessions, worktrees }, null, 2) + "\n", "utf-8");
}
function evidenceScopeKey(directory) {
    const cwd = directory.trim();
    if (!cwd) {
        return "";
    }
    try {
        const root = execFileSync("git", ["rev-parse", "--show-toplevel"], {
            cwd,
            stdio: ["ignore", "pipe", "ignore"],
        })
            .toString("utf-8")
            .trim();
        const branch = execFileSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
            cwd,
            stdio: ["ignore", "pipe", "ignore"],
        })
            .toString("utf-8")
            .trim();
        return `${root}::${branch || cwd}`;
    }
    catch {
        return cwd;
    }
}
function mergeEvidence(sessionSnapshot, worktreeSnapshot) {
    return {
        lint: sessionSnapshot.lint || worktreeSnapshot.lint,
        test: sessionSnapshot.test || worktreeSnapshot.test,
        typecheck: sessionSnapshot.typecheck || worktreeSnapshot.typecheck,
        build: sessionSnapshot.build || worktreeSnapshot.build,
        security: sessionSnapshot.security || worktreeSnapshot.security,
        updatedAt: sessionSnapshot.updatedAt || worktreeSnapshot.updatedAt,
    };
}
function computeMissing(snapshot, markers) {
    const missing = [];
    for (const marker of markers) {
        const normalized = marker.trim().toLowerCase();
        if (!normalized) {
            continue;
        }
        const category = markerCategory(normalized);
        if (!category) {
            missing.push(normalized);
            continue;
        }
        if (!snapshot[category]) {
            missing.push(normalized);
        }
    }
    return missing;
}
// Resolves evidence category for marker token when supported.
export function markerCategory(marker) {
    const value = marker.trim().toLowerCase();
    if (!value) {
        return null;
    }
    if (value.includes("lint")) {
        return "lint";
    }
    if (value.includes("test")) {
        return "test";
    }
    if (value.includes("type") || value.includes("tsc") || value.includes("mypy") || value.includes("pyright")) {
        return "typecheck";
    }
    if (value.includes("build") || value.includes("compile")) {
        return "build";
    }
    if (value.includes("security") ||
        value.includes("audit") ||
        value.includes("semgrep") ||
        value.includes("codeql")) {
        return "security";
    }
    return null;
}
// Returns immutable snapshot for session evidence.
export function validationEvidence(sessionId) {
    if (!sessionId.trim()) {
        return emptyEvidence();
    }
    const current = evidenceBySession.get(sessionId.trim());
    if (!current) {
        const persisted = readPersistedEvidence(process.cwd()).sessions[sessionId.trim()];
        if (persisted) {
            evidenceBySession.set(sessionId.trim(), persisted);
            return { ...persisted };
        }
        return emptyEvidence();
    }
    return { ...current };
}
// Returns immutable snapshot for worktree/branch-scoped evidence.
export function worktreeValidationEvidence(directory) {
    const key = evidenceScopeKey(directory);
    if (!key) {
        return emptyEvidence();
    }
    const current = evidenceByWorktree.get(key);
    if (!current) {
        const persisted = readPersistedEvidence(directory).worktrees[key];
        if (persisted) {
            evidenceByWorktree.set(key, persisted);
            return { ...persisted };
        }
        return emptyEvidence();
    }
    return { ...current };
}
// Marks one or more evidence categories as validated.
export function markValidationEvidence(sessionId, categories, directory = "") {
    const key = sessionId.trim();
    if (!key) {
        return emptyEvidence();
    }
    const next = {
        ...validationEvidence(key),
    };
    for (const category of categories) {
        next[category] = true;
    }
    next.updatedAt = new Date().toISOString();
    evidenceBySession.set(key, next);
    const scopeKey = evidenceScopeKey(directory);
    if (scopeKey) {
        const scoped = {
            ...worktreeValidationEvidence(directory),
        };
        for (const category of categories) {
            scoped[category] = true;
        }
        scoped.updatedAt = next.updatedAt;
        evidenceByWorktree.set(scopeKey, scoped);
    }
    writePersistedEvidence(directory);
    return { ...next };
}
// Clears evidence state for one session.
export function clearValidationEvidence(sessionId) {
    const key = sessionId.trim();
    if (!key) {
        return;
    }
    evidenceBySession.delete(key);
    const persisted = readPersistedEvidence(process.cwd());
    delete persisted.sessions[key];
    const filePath = evidenceFilePath(process.cwd());
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, JSON.stringify(persisted, null, 2) + "\n", "utf-8");
}
// Returns missing marker list based on current ledger evidence.
export function missingValidationMarkers(sessionId, markers) {
    return computeMissing(validationEvidence(sessionId), markers);
}
// Returns validation status across session and optional worktree fallback.
export function validationEvidenceStatus(sessionId, markers, directory = "") {
    const sessionSnapshot = validationEvidence(sessionId);
    const sessionMissing = computeMissing(sessionSnapshot, markers);
    if (sessionMissing.length === 0) {
        return { missing: [], source: "session" };
    }
    const worktreeSnapshot = worktreeValidationEvidence(directory);
    const worktreeMissing = computeMissing(worktreeSnapshot, markers);
    if (worktreeMissing.length === 0 && directory.trim()) {
        return { missing: [], source: "worktree" };
    }
    const merged = mergeEvidence(sessionSnapshot, worktreeSnapshot);
    const mergedMissing = computeMissing(merged, markers);
    if (mergedMissing.length === 0 && directory.trim()) {
        return { missing: [], source: "session+worktree" };
    }
    return { missing: mergedMissing, source: "none" };
}
