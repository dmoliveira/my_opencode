import { isProxy } from "node:util/types";
import { isCanonicalStructurallyValidPngDataUrl } from "./provider-attachment-data-url.js";
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
const MISSING_OWN_VALUE = Symbol("missing-own-value");
const OPAQUE_PNG_FALSE_POSITIVE_PATTERN_SOURCE = "AIza[0-9A-Za-z\\-_]{20,}";
const OPAQUE_PNG_FALSE_POSITIVE_PATTERN_FLAGS = "g";
const STANDARD_OBJECT_PROTOTYPE_KEYS = new Set([
    "constructor",
    "__defineGetter__",
    "__defineSetter__",
    "hasOwnProperty",
    "__lookupGetter__",
    "__lookupSetter__",
    "isPrototypeOf",
    "propertyIsEnumerable",
    "toString",
    "valueOf",
    "__proto__",
    "toLocaleString",
]);
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
function ownDataValue(value, key) {
    if (!value || typeof value !== "object" || isProxy(value)) {
        return MISSING_OWN_VALUE;
    }
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !("value" in descriptor)) {
        return MISSING_OWN_VALUE;
    }
    return descriptor.value;
}
function ownDataRecord(value, key) {
    const candidate = ownDataValue(value, key);
    return candidate && typeof candidate === "object" && !Array.isArray(candidate)
        ? candidate
        : null;
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
    return { index, source, flags: normalizedFlags };
}
function emptyStats() {
    return {
        matches: 0,
        redactedFields: 0,
        scannedChars: 0,
        scannedNodes: 0,
        omittedOpaquePngMatches: 0,
    };
}
export function createSecretRedactor(options) {
    const patterns = options.patterns.map(compilePattern);
    const omittableOpaquePngPatternIndex = Number.isInteger(options.omittableOpaquePngPatternIndex)
        ? options.omittableOpaquePngPatternIndex
        : null;
    const limits = {
        maxDepth: normalizedLimit(options.limits.maxDepth, 12),
        maxNodes: normalizedLimit(options.limits.maxNodes, 20_000),
        maxChars: normalizedLimit(options.limits.maxChars, 2 * 1024 * 1024),
    };
    const providerMaxNodes = normalizedLimit(options.providerLimits?.maxNodes ?? 0, 1_000_000);
    const providerMaxChars = normalizedLimit(options.providerLimits?.maxChars ?? 0, 128 * 1024 * 1024);
    const providerLimits = {
        maxMessages: Math.min(normalizedLimit(options.providerLimits?.maxMessages ?? 0, 20_000), providerMaxNodes),
        maxNodes: providerMaxNodes,
        maxChars: providerMaxChars,
        maxMessageChars: Math.min(normalizedLimit(options.providerLimits?.maxMessageChars ?? 0, 16 * 1024 * 1024), providerMaxChars),
    };
    function createBudget(maxNodes, maxChars) {
        return { nodes: 0, chars: 0, maxNodes, maxChars };
    }
    function chargeNode(state, localBudget) {
        state.budget.nodes += 1;
        if (state.budget.nodes > state.budget.maxNodes) {
            throw new SecretRedactionError("node_limit");
        }
        if (localBudget) {
            localBudget.nodes += 1;
            if (localBudget.nodes > localBudget.maxNodes) {
                throw new SecretRedactionError("node_limit");
            }
        }
        state.stats.scannedNodes += 1;
    }
    function chargeChars(text, budget, localBudget) {
        budget.chars += text.length;
        if (budget.chars > budget.maxChars) {
            throw new SecretRedactionError("text_limit");
        }
        if (localBudget) {
            localBudget.chars += text.length;
            if (localBudget.chars > localBudget.maxChars) {
                throw new SecretRedactionError("text_limit");
            }
        }
    }
    function applyPatterns(text, stats, budget, localBudget, applicationOptions = {}) {
        if (applicationOptions.charge !== false) {
            chargeChars(text, budget, localBudget);
        }
        stats.scannedChars += text.length;
        let next = text;
        let firstPatternIndex = null;
        for (const [patternIndex, pattern] of patterns.entries()) {
            if (applicationOptions.omitPattern?.(pattern))
                continue;
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
    function isTrustedOpenAIReasoningCiphertext(options) {
        const { messageRoot, parent, key, path, value } = options;
        if (key !== "reasoningEncryptedContent" ||
            path.length !== 5 ||
            path[0] !== "parts" ||
            !Number.isInteger(path[1]) ||
            path[2] !== "metadata" ||
            path[3] !== "openai" ||
            path[4] !== "reasoningEncryptedContent" ||
            value.length === 0) {
            return false;
        }
        const info = ownDataRecord(messageRoot, "info");
        const parts = ownDataValue(messageRoot, "parts");
        const partIndex = path[1];
        if (!info ||
            ownDataValue(info, "role") !== "assistant" ||
            ownDataValue(info, "providerID") !== "openai" ||
            !Array.isArray(parts) ||
            partIndex < 0 ||
            partIndex >= parts.length) {
            return false;
        }
        const part = ownDataValue(parts, partIndex);
        if (!part || typeof part !== "object" || ownDataValue(part, "type") !== "reasoning") {
            return false;
        }
        const metadata = ownDataRecord(part, "metadata");
        const openai = ownDataRecord(metadata, "openai");
        const itemId = ownDataValue(openai, "itemId");
        return (Boolean(openai) &&
            parent === openai &&
            typeof itemId === "string" &&
            /^rs_.+$/.test(itemId) &&
            ownDataValue(openai, "reasoningEncryptedContent") === value);
    }
    function qualifiedOpenAIPngAttachment(options) {
        const { messageRoot, parent, key, path, value } = options;
        if (key !== "url" ||
            path.length !== 6 ||
            path[0] !== "parts" ||
            !Number.isInteger(path[1]) ||
            path[2] !== "state" ||
            path[3] !== "attachments" ||
            !Number.isInteger(path[4]) ||
            path[5] !== "url") {
            return false;
        }
        const info = ownDataRecord(messageRoot, "info");
        const parts = ownDataValue(messageRoot, "parts");
        const partIndex = path[1];
        const attachmentIndex = path[4];
        if (!info ||
            ownDataValue(info, "role") !== "assistant" ||
            ownDataValue(info, "providerID") !== "openai" ||
            !Array.isArray(parts) ||
            partIndex < 0 ||
            partIndex >= parts.length) {
            return false;
        }
        const messageId = ownDataValue(info, "id");
        const sessionId = ownDataValue(info, "sessionID");
        const part = ownDataValue(parts, partIndex);
        if (typeof messageId !== "string" ||
            !messageId ||
            typeof sessionId !== "string" ||
            !sessionId ||
            !part ||
            typeof part !== "object" ||
            Array.isArray(part) ||
            ownDataValue(part, "type") !== "tool" ||
            typeof ownDataValue(part, "tool") !== "string" ||
            !ownDataValue(part, "tool") ||
            typeof ownDataValue(part, "callID") !== "string" ||
            !ownDataValue(part, "callID") ||
            typeof ownDataValue(part, "id") !== "string" ||
            !ownDataValue(part, "id") ||
            ownDataValue(part, "messageID") !== messageId ||
            ownDataValue(part, "sessionID") !== sessionId) {
            return false;
        }
        const state = ownDataRecord(part, "state");
        const attachments = ownDataValue(state, "attachments");
        const stateTime = ownDataRecord(state, "time");
        if (!state ||
            ownDataValue(state, "status") !== "completed" ||
            !stateTime ||
            ownDataValue(stateTime, "compacted") !== MISSING_OWN_VALUE ||
            "compacted" in stateTime ||
            !Array.isArray(attachments) ||
            attachmentIndex < 0 ||
            attachmentIndex >= attachments.length) {
            return false;
        }
        const attachment = ownDataValue(attachments, attachmentIndex);
        return (Boolean(attachment) &&
            typeof attachment === "object" &&
            !Array.isArray(attachment) &&
            parent === attachment &&
            ownDataValue(attachment, "type") === "file" &&
            ownDataValue(attachment, "mime") === "image/png" &&
            typeof ownDataValue(attachment, "id") === "string" &&
            Boolean(ownDataValue(attachment, "id")) &&
            typeof ownDataValue(attachment, "messageID") === "string" &&
            Boolean(ownDataValue(attachment, "messageID")) &&
            typeof ownDataValue(attachment, "sessionID") === "string" &&
            Boolean(ownDataValue(attachment, "sessionID")) &&
            ownDataValue(attachment, "url") === value);
    }
    function isOmittableOpaquePngPattern(pattern) {
        return (pattern.index === omittableOpaquePngPatternIndex &&
            pattern.source === OPAQUE_PNG_FALSE_POSITIVE_PATTERN_SOURCE &&
            pattern.flags === OPAQUE_PNG_FALSE_POSITIVE_PATTERN_FLAGS);
    }
    function opaquePngCollisionCount(value) {
        let count = 0;
        for (const pattern of patterns) {
            if (!isOmittableOpaquePngPattern(pattern))
                continue;
            const regex = new RegExp(pattern.source, pattern.flags);
            while (regex.exec(value))
                count += 1;
        }
        return count;
    }
    function canChargeChars(value, budget, localBudget) {
        return (value.length <= budget.maxChars - budget.chars &&
            (!localBudget || value.length <= localBudget.maxChars - localBudget.chars));
    }
    function toolStateMetadataProjection(options) {
        const { messageRoot, parent, path, value } = options;
        if (path.length !== 4 ||
            path[0] !== "parts" ||
            !Number.isInteger(path[1]) ||
            path[2] !== "state" ||
            path[3] !== "metadata") {
            return null;
        }
        const info = ownDataRecord(messageRoot, "info");
        const parts = ownDataValue(messageRoot, "parts");
        const partIndex = path[1];
        if (!info ||
            ownDataValue(info, "role") !== "assistant" ||
            !Array.isArray(parts) ||
            partIndex < 0 ||
            partIndex >= parts.length) {
            return null;
        }
        const part = ownDataValue(parts, partIndex);
        if (!part ||
            typeof part !== "object" ||
            Array.isArray(part) ||
            ownDataValue(part, "type") !== "tool") {
            return null;
        }
        const state = ownDataRecord(part, "state");
        const metadata = ownDataRecord(state, "metadata");
        if (!state || parent !== state || !metadata || value !== metadata) {
            return null;
        }
        const status = ownDataValue(state, "status");
        if (status === "completed" || status === "pending" || status === "running") {
            return { kind: "skip" };
        }
        if (status !== "error") {
            throw new SecretRedactionError("malformed_provider_metadata");
        }
        const interrupted = ownDataValue(metadata, "interrupted");
        if (interrupted === MISSING_OWN_VALUE) {
            if ("interrupted" in metadata) {
                throw new SecretRedactionError("malformed_provider_metadata");
            }
            return { kind: "skip" };
        }
        if (interrupted === false) {
            return { kind: "skip" };
        }
        if (interrupted !== true) {
            throw new SecretRedactionError("malformed_provider_metadata");
        }
        const output = ownDataValue(metadata, "output");
        if (output === MISSING_OWN_VALUE && !("output" in metadata)) {
            return { kind: "skip" };
        }
        if (typeof output !== "string") {
            throw new SecretRedactionError("malformed_provider_metadata");
        }
        return { kind: "output", value: output };
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
    function createTraversalState(traversalLimits, revisitAliases, strictProviderObjects = false) {
        if (strictProviderObjects) {
            const prototypeKeys = Reflect.ownKeys(Object.prototype);
            if (prototypeKeys.length !== STANDARD_OBJECT_PROTOTYPE_KEYS.size ||
                prototypeKeys.some((key) => !STANDARD_OBJECT_PROTOTYPE_KEYS.has(key))) {
                throw new SecretRedactionError("malformed_provider_object");
            }
        }
        return {
            stats: emptyStats(),
            budget: createBudget(traversalLimits.maxNodes, traversalLimits.maxChars),
            maxDepth: traversalLimits.maxDepth,
            active: new WeakSet(),
            visited: new WeakSet(),
            revisitAliases,
            strictProviderObjects,
        };
    }
    function providerOwnDataChildren(value, maxChildren) {
        if (isProxy(value)) {
            throw new SecretRedactionError("malformed_provider_object");
        }
        const prototype = Object.getPrototypeOf(value);
        const isArray = Array.isArray(value);
        if ((isArray && prototype !== Array.prototype) ||
            (!isArray && prototype !== Object.prototype && prototype !== null)) {
            throw new SecretRedactionError("malformed_provider_object");
        }
        const ownKeys = Reflect.ownKeys(value);
        if (isArray) {
            const array = value;
            if (array.length > maxChildren || ownKeys.length !== array.length + 1) {
                throw new SecretRedactionError(array.length > maxChildren ? "node_limit" : "malformed_provider_object");
            }
            const children = [];
            for (let index = 0; index < array.length; index += 1) {
                const descriptor = Object.getOwnPropertyDescriptor(array, String(index));
                if (!descriptor || !("value" in descriptor) || !descriptor.enumerable) {
                    throw new SecretRedactionError("malformed_provider_object");
                }
                children.push([index, descriptor.value]);
            }
            const lengthDescriptor = Object.getOwnPropertyDescriptor(array, "length");
            if (!lengthDescriptor ||
                !("value" in lengthDescriptor) ||
                lengthDescriptor.value !== array.length ||
                ownKeys.some((key) => typeof key !== "string" ||
                    (key !== "length" &&
                        (!/^(?:0|[1-9][0-9]*)$/.test(key) || Number(key) >= array.length)))) {
                throw new SecretRedactionError("malformed_provider_object");
            }
            return children;
        }
        if (ownKeys.length > maxChildren) {
            throw new SecretRedactionError("node_limit");
        }
        const children = [];
        for (const childKey of ownKeys) {
            if (typeof childKey !== "string") {
                throw new SecretRedactionError("malformed_provider_object");
            }
            const descriptor = Object.getOwnPropertyDescriptor(value, childKey);
            if (!descriptor || !("value" in descriptor) || !descriptor.enumerable) {
                throw new SecretRedactionError("malformed_provider_object");
            }
            children.push([childKey, descriptor.value]);
        }
        return children;
    }
    function remainingNodeBudget(state, localBudget) {
        return Math.min(state.budget.maxNodes - state.budget.nodes, localBudget ? localBudget.maxNodes - localBudget.nodes : Number.POSITIVE_INFINITY);
    }
    function visit(value, parent, key, mode, depth, parentKey, grandparentKey, path, state, localBudget, messageRoot) {
        chargeNode(state, localBudget);
        if (depth > state.maxDepth) {
            throw new SecretRedactionError("depth_limit");
        }
        if (state.strictProviderObjects &&
            (value === undefined ||
                typeof value === "function" ||
                typeof value === "symbol" ||
                typeof value === "bigint" ||
                (typeof value === "number" && !Number.isFinite(value)))) {
            throw new SecretRedactionError("malformed_provider_object");
        }
        if (typeof value === "string") {
            if (messageRoot !== undefined &&
                isTrustedOpenAIReasoningCiphertext({ messageRoot, parent, key, path, value })) {
                chargeChars(value, state.budget, localBudget);
                return;
            }
            if (messageRoot !== undefined &&
                qualifiedOpenAIPngAttachment({ messageRoot, parent, key, path, value })) {
                if (!canChargeChars(value, state.budget, localBudget)) {
                    chargeChars(value, state.budget, localBudget);
                }
                const omittedCollisionCount = opaquePngCollisionCount(value);
                if (omittedCollisionCount > 0 &&
                    isCanonicalStructurallyValidPngDataUrl(value)) {
                    chargeChars(value, state.budget, localBudget);
                    state.stats.omittedOpaquePngMatches += omittedCollisionCount;
                    const applied = applyPatterns(value, state.stats, state.budget, localBudget, {
                        charge: false,
                        omitPattern: isOmittableOpaquePngPattern,
                    });
                    if (applied.text === value)
                        return;
                    throw immutableMatchError({
                        matchTarget: "value",
                        patternIndex: applied.firstPatternIndex,
                        key,
                        parentKey,
                        grandparentKey,
                    });
                }
            }
            const applied = applyPatterns(value, state.stats, state.budget, localBudget);
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
            state.stats.redactedFields += 1;
            return;
        }
        const strictChildren = state.strictProviderObjects && value && typeof value === "object"
            ? providerOwnDataChildren(value, remainingNodeBudget(state, localBudget))
            : null;
        if (messageRoot !== undefined) {
            const projection = toolStateMetadataProjection({ messageRoot, parent, path, value });
            if (projection) {
                if (projection.kind === "output") {
                    const outputKey = "output";
                    const keyProbe = applyPatterns(outputKey, state.stats, state.budget, localBudget);
                    if (keyProbe.text !== outputKey) {
                        throw immutableMatchError({
                            matchTarget: "key",
                            patternIndex: keyProbe.firstPatternIndex,
                            key: outputKey,
                            parentKey: key,
                            grandparentKey: parentKey,
                        });
                    }
                    visit(projection.value, value, outputKey, "redact", depth + 1, key, parentKey, [...path, outputKey], state, localBudget, messageRoot);
                }
                return;
            }
        }
        if (!value || typeof value !== "object") {
            return;
        }
        if (state.active.has(value)) {
            throw new SecretRedactionError("cycle_detected");
        }
        if (!state.revisitAliases && state.visited.has(value)) {
            return;
        }
        state.active.add(value);
        if (Array.isArray(value)) {
            if (strictChildren) {
                for (const [index, child] of strictChildren) {
                    visit(child, value, index, mode, depth + 1, key, parentKey, [...path, index], state, localBudget, messageRoot);
                }
            }
            else {
                for (let index = 0; index < value.length; index += 1) {
                    visit(value[index], value, index, mode, depth + 1, key, parentKey, [...path, index], state, localBudget, messageRoot);
                }
            }
        }
        else {
            const record = value;
            const children = strictChildren ??
                Object.keys(record).map((childKey) => [childKey, record[childKey]]);
            for (const [childKey, child] of children) {
                if (typeof childKey !== "string") {
                    throw new SecretRedactionError("malformed_provider_object");
                }
                const keyProbe = applyPatterns(childKey, state.stats, state.budget, localBudget);
                if (keyProbe.text !== childKey) {
                    throw immutableMatchError({
                        matchTarget: "key",
                        patternIndex: keyProbe.firstPatternIndex,
                        key: childKey,
                        parentKey: key,
                        grandparentKey: parentKey,
                    });
                }
                visit(child, record, childKey, childMode(mode, childKey), depth + 1, key, parentKey, [...path, childKey], state, localBudget, messageRoot);
            }
        }
        state.active.delete(value);
        state.visited.add(value);
    }
    function traverse(root, initialMode, strictProviderObjects = false) {
        const state = createTraversalState(limits, false, strictProviderObjects);
        try {
            visit(root, null, null, initialMode, 0, null, null, [], state);
            return state.stats;
        }
        catch (error) {
            if (error instanceof SecretRedactionError) {
                throw error;
            }
            throw new SecretRedactionError("unexpected_failure");
        }
    }
    function traverseProviderMessages(messages) {
        if (messages && typeof messages === "object" && isProxy(messages)) {
            throw new SecretRedactionError("malformed_provider_object");
        }
        if (!Array.isArray(messages)) {
            return traverse(messages, "scan", true);
        }
        if (messages.length > providerLimits.maxMessages) {
            throw new SecretRedactionError("node_limit");
        }
        const state = createTraversalState({
            maxDepth: limits.maxDepth,
            maxNodes: providerLimits.maxNodes,
            maxChars: providerLimits.maxChars,
        }, true, true);
        try {
            chargeNode(state);
            const messageEntries = providerOwnDataChildren(messages, state.budget.maxNodes - state.budget.nodes);
            state.active.add(messages);
            for (const [index, message] of messageEntries) {
                const localBudget = createBudget(limits.maxNodes, providerLimits.maxMessageChars);
                visit(message, messages, index, "scan", 1, null, null, [], state, localBudget, message);
            }
            state.active.delete(messages);
            state.visited.add(messages);
            return state.stats;
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
            const budget = createBudget(limits.maxNodes, limits.maxChars);
            const redacted = applyPatterns(text, stats, budget);
            if (redacted.text !== text) {
                stats.redactedFields = 1;
            }
            return { text: redacted.text, stats };
        },
        redactMutableValue(value) {
            return traverse(value, "redact");
        },
        redactProviderMessages(messages) {
            return traverseProviderMessages(messages);
        },
        redactProviderSystem(system) {
            return traverse(system, "redact", true);
        },
    };
}
