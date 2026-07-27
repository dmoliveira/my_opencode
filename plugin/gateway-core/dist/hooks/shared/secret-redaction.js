export class SecretRedactionError extends Error {
    code;
    matchTarget;
    patternIndex;
    locationCode;
    constructor(code, detail = "", diagnostics = null) {
        super(`secret redaction blocked: ${code}${detail ? ` (${detail})` : ""}`);
        this.name = "SecretRedactionError";
        this.code = code;
        this.matchTarget = diagnostics?.matchTarget ?? null;
        this.patternIndex = diagnostics?.patternIndex ?? null;
        this.locationCode = diagnostics?.locationCode ?? null;
    }
}
const MUTABLE_CONTENT_KEYS = new Set([
    "after",
    "before",
    "body",
    "content",
    "description",
    "diff",
    "diffs",
    "error",
    "input",
    "message",
    "output",
    "prompt",
    "reasoning",
    "source",
    "summary",
    "system",
    "text",
    "title",
]);
const IMMUTABLE_PROTOCOL_KEYS = new Set([
    "callID",
    "filename",
    "id",
    "messageID",
    "metadata",
    "mime",
    "modelID",
    "path",
    "providerID",
    "role",
    "sessionID",
    "tool",
    "type",
    "url",
]);
function normalizedLimit(value, fallback) {
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}
function compilePattern(rawPattern, index) {
    let source = rawPattern;
    const flags = new Set(["g"]);
    while (true) {
        const match = source.match(/^\(\?([ims]+)\)/);
        if (!match) {
            break;
        }
        for (const flag of match[1] ?? "") {
            flags.add(flag);
        }
        source = source.slice(match[0].length);
    }
    const normalizedFlags = ["g", "i", "m", "s"].filter((flag) => flags.has(flag)).join("");
    try {
        // Compile once here to reject malformed configured patterns without exposing them.
        new RegExp(source, normalizedFlags);
    }
    catch {
        throw new SecretRedactionError("invalid_pattern", `index=${index}`);
    }
    return { source, flags: normalizedFlags };
}
function emptyStats() {
    return { matches: 0, redactedFields: 0, scannedChars: 0, scannedNodes: 0 };
}
export function createSecretRedactor(options) {
    const patterns = options.patterns.map(compilePattern);
    const limits = {
        maxDepth: normalizedLimit(options.limits.maxDepth, 12),
        maxNodes: normalizedLimit(options.limits.maxNodes, 20_000),
        maxChars: normalizedLimit(options.limits.maxChars, 2 * 1024 * 1024),
    };
    function applyPatterns(text, stats) {
        stats.scannedChars += text.length;
        if (stats.scannedChars > limits.maxChars) {
            throw new SecretRedactionError("text_limit");
        }
        let next = text;
        let firstPatternIndex = null;
        for (const [patternIndex, pattern] of patterns.entries()) {
            const regex = new RegExp(pattern.source, pattern.flags);
            next = next.replace(regex, () => {
                firstPatternIndex ??= patternIndex;
                stats.matches += 1;
                return options.redactionToken;
            });
        }
        return { text: next, firstPatternIndex };
    }
    function locationCode(key, parentKey, grandparentKey) {
        if (parentKey === "openai" && grandparentKey === "metadata") {
            return key === "itemId"
                ? "provider_metadata_openai_item_id"
                : "provider_metadata_openai_other";
        }
        if (typeof key === "string" && IMMUTABLE_PROTOCOL_KEYS.has(key)) {
            return "immutable_protocol_field";
        }
        return "unknown_field";
    }
    function immutableMatchError(options) {
        if (options.patternIndex === null) {
            return new SecretRedactionError("unexpected_failure");
        }
        return new SecretRedactionError("immutable_match", "", {
            matchTarget: options.matchTarget,
            patternIndex: options.patternIndex,
            locationCode: locationCode(options.key, options.parentKey, options.grandparentKey),
        });
    }
    function assignValue(parent, key, value) {
        if (parent === null || key === null) {
            throw new SecretRedactionError("mutation_failed");
        }
        try {
            if (Array.isArray(parent) && typeof key === "number") {
                parent[key] = value;
            }
            else if (!Array.isArray(parent) && typeof key === "string") {
                parent[key] = value;
            }
            else {
                throw new SecretRedactionError("mutation_failed");
            }
        }
        catch (error) {
            if (error instanceof SecretRedactionError) {
                throw error;
            }
            throw new SecretRedactionError("mutation_failed");
        }
    }
    function childMode(parentMode, key) {
        if (IMMUTABLE_PROTOCOL_KEYS.has(key)) {
            return "scan";
        }
        if (MUTABLE_CONTENT_KEYS.has(key)) {
            return "redact";
        }
        return parentMode;
    }
    function traverse(root, initialMode) {
        const stats = emptyStats();
        const active = new WeakSet();
        const visited = new WeakSet();
        function visit(value, parent, key, mode, depth, parentKey, grandparentKey) {
            stats.scannedNodes += 1;
            if (stats.scannedNodes > limits.maxNodes) {
                throw new SecretRedactionError("node_limit");
            }
            if (depth > limits.maxDepth) {
                throw new SecretRedactionError("depth_limit");
            }
            if (typeof value === "string") {
                const applied = applyPatterns(value, stats);
                if (applied.text === value) {
                    return;
                }
                if (mode === "scan") {
                    throw immutableMatchError({
                        matchTarget: "value",
                        patternIndex: applied.firstPatternIndex,
                        key,
                        parentKey,
                        grandparentKey,
                    });
                }
                assignValue(parent, key, applied.text);
                stats.redactedFields += 1;
                return;
            }
            if (!value || typeof value !== "object") {
                return;
            }
            if (active.has(value)) {
                throw new SecretRedactionError("cycle_detected");
            }
            if (visited.has(value)) {
                return;
            }
            active.add(value);
            if (Array.isArray(value)) {
                for (let index = 0; index < value.length; index += 1) {
                    visit(value[index], value, index, mode, depth + 1, key, parentKey);
                }
            }
            else {
                const record = value;
                for (const childKey of Object.keys(record)) {
                    const keyProbe = applyPatterns(childKey, stats);
                    if (keyProbe.text !== childKey) {
                        throw immutableMatchError({
                            matchTarget: "key",
                            patternIndex: keyProbe.firstPatternIndex,
                            key: childKey,
                            parentKey: key,
                            grandparentKey: parentKey,
                        });
                    }
                    visit(record[childKey], record, childKey, childMode(mode, childKey), depth + 1, key, parentKey);
                }
            }
            active.delete(value);
            visited.add(value);
        }
        try {
            visit(root, null, null, initialMode, 0, null, null);
            return stats;
        }
        catch (error) {
            if (error instanceof SecretRedactionError) {
                throw error;
            }
            throw new SecretRedactionError("unexpected_failure");
        }
    }
    return {
        redactText(text) {
            const stats = emptyStats();
            const redacted = applyPatterns(text, stats);
            if (redacted.text !== text) {
                stats.redactedFields = 1;
            }
            return { text: redacted.text, stats };
        },
        redactMutableValue(value) {
            return traverse(value, "redact");
        },
        redactProviderMessages(messages) {
            return traverse(messages, "scan");
        },
        redactProviderSystem(system) {
            return traverse(system, "redact");
        },
    };
}
