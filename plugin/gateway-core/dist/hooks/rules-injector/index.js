import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { basename, join, relative, sep } from "node:path";
import { writeGatewayEventAudit } from "../../audit/event-audit.js";
const TRACKED_TOOLS = new Set(["read", "write", "edit", "multiedit"]);
const RULES_DIRS = [
    [".github", "instructions"],
    [".claude", "rules"],
    [".cursor", "rules"],
    [".sisyphus", "rules"],
];
// Resolves stable session id from tool lifecycle payloads.
function resolveSessionId(payload) {
    const candidates = [payload.input?.sessionID, payload.input?.sessionId];
    for (const value of candidates) {
        if (typeof value === "string" && value.trim()) {
            return value.trim();
        }
    }
    return "";
}
// Converts filesystem path to slash-normalized form.
function toSlashPath(value) {
    return value.replaceAll(sep, "/");
}
// Parses a bracketed inline array into string entries.
function parseInlineArrayValues(raw) {
    const trimmed = raw.trim();
    if (!(trimmed.startsWith("[") && trimmed.endsWith("]"))) {
        return [];
    }
    const entries = [];
    const matches = trimmed.matchAll(/"([^"]+)"|'([^']+)'/g);
    for (const match of matches) {
        const value = match[1] ?? match[2] ?? "";
        if (value.trim()) {
            entries.push(value.trim());
        }
    }
    if (entries.length > 0) {
        return entries;
    }
    return trimmed
        .slice(1, -1)
        .split(",")
        .map((part) => part.trim().replace(/^['"]|['"]$/g, ""))
        .filter((part) => part.length > 0);
}
// Expands simple brace globs like *.{ts,tsx}.
function expandBraceGlobs(pattern) {
    const start = pattern.indexOf("{");
    const end = pattern.indexOf("}");
    if (start < 0 || end < 0 || end <= start + 1) {
        return [pattern];
    }
    const prefix = pattern.slice(0, start);
    const suffix = pattern.slice(end + 1);
    const choices = pattern
        .slice(start + 1, end)
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part.length > 0);
    if (choices.length === 0) {
        return [pattern];
    }
    const expanded = [];
    for (const choice of choices) {
        for (const next of expandBraceGlobs(`${prefix}${choice}${suffix}`)) {
            expanded.push(next);
        }
    }
    return expanded;
}
// Converts a basic glob pattern to a regular expression.
function globToRegex(glob) {
    const escaped = glob
        .replace(/[.+^${}()|[\]\\]/g, "\\$&")
        .replace(/\*\*/g, "::DOUBLE_STAR::")
        .replace(/\*/g, "[^/]*")
        .replace(/::DOUBLE_STAR::/g, ".*");
    return new RegExp(`^${escaped}$`);
}
// Returns true when relative path matches any provided glob.
function matchesAnyGlob(relativePath, globs) {
    const normalized = toSlashPath(relativePath);
    for (const pattern of globs) {
        const trimmed = pattern.trim();
        if (!trimmed) {
            continue;
        }
        for (const expanded of expandBraceGlobs(trimmed)) {
            if (globToRegex(expanded).test(normalized)) {
                return true;
            }
            if (expanded.includes("**/")) {
                const optionalParentPattern = expanded.replace("**/", "");
                if (globToRegex(optionalParentPattern).test(normalized)) {
                    return true;
                }
            }
            if (expanded.startsWith("*/")) {
                const optionalPrefixPattern = expanded.slice(2);
                if (globToRegex(optionalPrefixPattern).test(normalized)) {
                    return true;
                }
            }
            if (expanded.startsWith("**/")) {
                const rootPattern = expanded.slice(3);
                if (globToRegex(rootPattern).test(normalized)) {
                    return true;
                }
            }
            if (expanded.startsWith("./") && globToRegex(expanded.slice(2)).test(normalized)) {
                return true;
            }
        }
    }
    return false;
}
// Parses simple markdown frontmatter with alwaysApply and applyTo values.
function parseRuleFile(path) {
    let content = "";
    try {
        content = readFileSync(path, "utf-8");
    }
    catch {
        return null;
    }
    const normalized = content.trim();
    if (!normalized) {
        return null;
    }
    const lines = normalized.split(/\r?\n/);
    let alwaysApply = basename(path).toLowerCase() === "copilot-instructions.md";
    const applyTo = [];
    let body = normalized;
    if (lines[0] === "---") {
        let end = -1;
        for (let idx = 1; idx < lines.length; idx += 1) {
            if (lines[idx] === "---") {
                end = idx;
                break;
            }
        }
        if (end > 0) {
            const frontmatter = lines.slice(1, end);
            body = lines.slice(end + 1).join("\n").trim();
            for (let idx = 0; idx < frontmatter.length; idx += 1) {
                const line = frontmatter[idx];
                const [rawKey, ...rawValueParts] = line.split(":");
                const key = rawKey.trim().toLowerCase();
                const value = rawValueParts.join(":").trim();
                if (!key) {
                    continue;
                }
                if (key === "alwaysapply") {
                    if (!value) {
                        continue;
                    }
                    alwaysApply = value.toLowerCase() === "true";
                    continue;
                }
                if (key === "applyto" || key === "glob" || key === "path") {
                    if (value.startsWith("[") && value.endsWith("]")) {
                        for (const part of parseInlineArrayValues(value)) {
                            if (part) {
                                applyTo.push(part);
                            }
                        }
                        continue;
                    }
                    if (!value) {
                        for (let listIndex = idx + 1; listIndex < frontmatter.length; listIndex += 1) {
                            const candidate = frontmatter[listIndex].trim();
                            if (!candidate.startsWith("- ")) {
                                break;
                            }
                            const normalizedItem = candidate.slice(2).trim().replace(/^['"]|['"]$/g, "");
                            if (normalizedItem) {
                                applyTo.push(normalizedItem);
                            }
                            idx = listIndex;
                        }
                        continue;
                    }
                    applyTo.push(value.replace(/^['"]|['"]$/g, ""));
                }
            }
        }
    }
    if (!body.trim()) {
        return null;
    }
    return {
        path,
        body: body.trim(),
        applyTo,
        alwaysApply,
    };
}
// Collects rule files from common project directories.
function collectRuleFiles(directory) {
    const results = [];
    const copilotPath = join(directory, ".github", "copilot-instructions.md");
    if (existsSync(copilotPath)) {
        const parsed = parseRuleFile(copilotPath);
        if (parsed) {
            results.push(parsed);
        }
    }
    for (const segments of RULES_DIRS) {
        const root = join(directory, ...segments);
        if (!existsSync(root)) {
            continue;
        }
        const stack = [root];
        while (stack.length > 0) {
            const current = stack.pop();
            if (!current) {
                continue;
            }
            for (const entry of readdirSync(current, { withFileTypes: true })) {
                const child = join(current, entry.name);
                if (entry.isDirectory()) {
                    stack.push(child);
                    continue;
                }
                if (!entry.isFile() || !entry.name.endsWith(".md")) {
                    continue;
                }
                const parsed = parseRuleFile(child);
                if (parsed) {
                    results.push(parsed);
                }
            }
        }
    }
    return results;
}
// Resolves target file path from tool output metadata/title.
function resolveTargetPath(output) {
    const metadataPath = output?.metadata?.filePath;
    if (typeof metadataPath === "string" && metadataPath.trim()) {
        return metadataPath.trim();
    }
    const title = output?.title;
    if (typeof title === "string" && title.trim()) {
        const match = title.match(/([\w./\\-]+\.[a-zA-Z0-9]+)/);
        if (match?.[1]) {
            return match[1];
        }
    }
    return "";
}
// Finds matching rules for the current file target.
function matchRules(rules, targetPath) {
    const matches = [];
    for (const rule of rules) {
        if (rule.alwaysApply) {
            matches.push({ rule, reason: "alwaysApply" });
            continue;
        }
        if (!targetPath || rule.applyTo.length === 0) {
            continue;
        }
        if (matchesAnyGlob(targetPath, rule.applyTo)) {
            matches.push({ rule, reason: `applyTo:${rule.applyTo[0]}` });
        }
    }
    return matches;
}
// Creates rules injector that appends file-aware guidance from markdown rule files.
export function createRulesInjectorHook(options) {
    const pendingToolBySession = new Map();
    const injectedStateBySession = new Map();
    const ruleCacheByDirectory = new Map();
    function clearSession(sessionId) {
        pendingToolBySession.delete(sessionId);
        injectedStateBySession.delete(sessionId);
    }
    return {
        id: "rules-injector",
        priority: 298,
        async event(type, payload) {
            if (!options.enabled) {
                return;
            }
            if (type === "session.deleted" || type === "session.compacted") {
                const eventPayload = (payload ?? {});
                const sessionId = eventPayload.properties?.info?.id;
                if (typeof sessionId === "string" && sessionId.trim()) {
                    clearSession(sessionId.trim());
                }
                return;
            }
            if (type === "tool.execute.before") {
                const eventPayload = (payload ?? {});
                const sessionId = resolveSessionId(eventPayload);
                const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
                if (sessionId && TRACKED_TOOLS.has(tool)) {
                    pendingToolBySession.set(sessionId, tool);
                }
                return;
            }
            if (type !== "tool.execute.after") {
                return;
            }
            const eventPayload = (payload ?? {});
            const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
                ? eventPayload.directory
                : options.directory;
            const sessionId = resolveSessionId(eventPayload);
            if (!sessionId) {
                return;
            }
            const pendingTool = pendingToolBySession.get(sessionId);
            pendingToolBySession.delete(sessionId);
            if (!pendingTool || !TRACKED_TOOLS.has(pendingTool) || typeof eventPayload.output?.output !== "string") {
                return;
            }
            let cachedRules = ruleCacheByDirectory.get(directory);
            if (!cachedRules) {
                cachedRules = collectRuleFiles(directory);
                ruleCacheByDirectory.set(directory, cachedRules);
            }
            if (cachedRules.length === 0) {
                return;
            }
            const targetPath = resolveTargetPath(eventPayload.output);
            const relativeTarget = targetPath ? toSlashPath(relative(directory, join(directory, targetPath))) : "";
            const matches = matchRules(cachedRules, relativeTarget);
            if (matches.length === 0) {
                return;
            }
            const state = injectedStateBySession.get(sessionId) ?? { hashes: new Set() };
            const blocks = [];
            for (const match of matches) {
                const hash = createHash("sha1").update(match.rule.path).update("\n").update(match.rule.body).digest("hex");
                if (state.hashes.has(hash)) {
                    continue;
                }
                state.hashes.add(hash);
                blocks.push(`[Rule: ${match.rule.path}]\n[Match: ${match.reason}]\n${match.rule.body}`);
            }
            injectedStateBySession.set(sessionId, state);
            if (blocks.length === 0) {
                return;
            }
            eventPayload.output.output = `${eventPayload.output.output}\n\n${blocks.join("\n\n")}`;
            writeGatewayEventAudit(directory, {
                hook: "rules-injector",
                stage: "state",
                reason_code: "runtime_rule_injected",
                session_id: sessionId,
                matched_rule_count: blocks.length,
                tool: pendingTool,
            });
        },
    };
}
