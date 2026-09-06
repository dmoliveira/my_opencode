import { createHash } from "node:crypto";
import { parentPort } from "node:worker_threads";
import { SECRET_REDACTION_WORKER_PROTOCOL_VERSION, } from "./secret-redaction-worker-protocol.js";
const MAX_PATTERN_COUNT = 64;
const MAX_PATTERN_SOURCE_BYTES = 16 * 1024;
const MAX_PATTERN_TOTAL_BYTES = 128 * 1024;
const MAX_MATCH_SPANS = 100_000;
const MAX_OUTPUT_CHARS = 64 * 1024 * 1024;
const LINEAR_OPAQUE_PATTERN_SOURCE = "AIza[0-9A-Za-z\\-_]{20,}";
class WorkerFailure extends Error {
    code;
    constructor(code) {
        super(code);
        this.code = code;
    }
}
function isRecord(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function validPatternSource(source) {
    return (typeof source === "string" &&
        Buffer.byteLength(source, "utf8") <= MAX_PATTERN_SOURCE_BYTES);
}
function compilePatterns(rawPatterns) {
    if (!Array.isArray(rawPatterns) || rawPatterns.length > MAX_PATTERN_COUNT) {
        throw new WorkerFailure("invalid_pattern");
    }
    let totalBytes = 0;
    const patterns = [];
    for (let index = 0; index < rawPatterns.length; index += 1) {
        const raw = rawPatterns[index];
        if (!isRecord(raw) ||
            raw.index !== index ||
            !validPatternSource(raw.source)) {
            throw new WorkerFailure("invalid_pattern");
        }
        if (typeof raw.flags !== "string" || !/^g[ims]{0,3}$/.test(raw.flags)) {
            throw new WorkerFailure("invalid_pattern");
        }
        totalBytes += Buffer.byteLength(raw.source, "utf8");
        if (totalBytes > MAX_PATTERN_TOTAL_BYTES) {
            throw new WorkerFailure("invalid_pattern");
        }
        try {
            new RegExp(raw.source, raw.flags);
        }
        catch {
            throw new WorkerFailure("invalid_pattern");
        }
        patterns.push({
            index,
            source: raw.source,
            flags: raw.flags,
            compiled: true,
        });
    }
    return patterns;
}
function collectMatches(value, pattern, budget) {
    const regex = new RegExp(pattern.source, pattern.flags);
    const matches = [];
    for (let match = regex.exec(value); match; match = regex.exec(value)) {
        if (budget.matchSpans >= MAX_MATCH_SPANS) {
            throw new WorkerFailure("unexpected_failure");
        }
        budget.matchSpans += 1;
        matches.push({ start: match.index, end: match.index + match[0].length });
        if (match[0].length === 0)
            regex.lastIndex += 1;
    }
    return matches;
}
function hasMatch(value, pattern) {
    return new RegExp(pattern.source, pattern.flags).test(value);
}
function replacementLength(valueLength, matches, replacementLength, budget) {
    let length = valueLength;
    for (const match of matches) {
        length += replacementLength - (match.end - match.start);
        if (length > MAX_OUTPUT_CHARS) {
            throw new WorkerFailure("unexpected_failure");
        }
    }
    budget.outputChars += length;
    if (budget.outputChars > MAX_OUTPUT_CHARS) {
        throw new WorkerFailure("unexpected_failure");
    }
    return length;
}
function replaceMatches(value, matches, replacement, budget) {
    if (matches.length === 0)
        return value;
    replacementLength(value.length, matches, replacement.length, budget);
    const parts = [];
    let cursor = 0;
    for (const match of matches) {
        parts.push(value.slice(cursor, match.start), replacement);
        cursor = match.end;
    }
    parts.push(value.slice(cursor));
    return parts.join("");
}
function applyOperation(operation, patterns, redactionToken, outputs, budget) {
    const input = operation.inputOperationIndex === null
        ? operation.text
        : outputs.get(operation.inputOperationIndex);
    if (input === undefined)
        throw new WorkerFailure("unexpected_failure");
    let current = input;
    let firstPatternIndex = null;
    let matchCount = 0;
    let positiveExpansion = 0;
    const steps = [];
    for (const pattern of patterns) {
        const matches = collectMatches(current, pattern, budget);
        if (matches.length > 0)
            firstPatternIndex ??= pattern.index;
        for (const match of matches) {
            matchCount += 1;
            positiveExpansion += Math.max(0, redactionToken.length - (match.end - match.start));
        }
        steps.push({ patternIndex: pattern.index, matches });
        current = replaceMatches(current, matches, redactionToken, budget);
    }
    let residualPatternIndex = null;
    if (firstPatternIndex !== null) {
        for (const pattern of patterns) {
            if (hasMatch(current, pattern)) {
                residualPatternIndex = pattern.index;
                break;
            }
        }
    }
    return {
        result: {
            operationIndex: operation.operationIndex,
            kind: "apply",
            inputLength: input.length,
            steps,
            firstPatternIndex,
            matchCount,
            positiveExpansion,
            residualPatternIndex,
            finalLength: current.length,
            finalSha256: createHash("sha256").update(current, "utf8").digest("hex"),
        },
        output: current,
    };
}
function attachmentResult(operation, patterns, outputs, budget) {
    const input = operation.inputOperationIndex === null
        ? operation.text
        : outputs.get(operation.inputOperationIndex);
    if (input === undefined)
        throw new WorkerFailure("unexpected_failure");
    let omittedMatchCount = 0;
    let matchSpanCount = 0;
    for (const pattern of patterns) {
        const matches = collectMatches(input, pattern, budget);
        matchSpanCount += matches.length;
        for (const match of matches) {
            const omittable = pattern.index === operation.omittablePatternIndex &&
                pattern.source === LINEAR_OPAQUE_PATTERN_SOURCE &&
                pattern.flags === "g" &&
                operation.payloadStart !== null &&
                operation.payloadEnd !== null &&
                match.start >= operation.payloadStart &&
                match.end <= operation.payloadEnd;
            if (omittable) {
                omittedMatchCount += 1;
                continue;
            }
            return {
                operationIndex: operation.operationIndex,
                kind: "attachment",
                inputLength: input.length,
                blockingPatternIndex: pattern.index,
                matchSpanCount,
                omittedMatchCount: 0,
            };
        }
    }
    return {
        operationIndex: operation.operationIndex,
        kind: "attachment",
        inputLength: input.length,
        blockingPatternIndex: null,
        matchSpanCount,
        omittedMatchCount,
    };
}
function matchResult(operation, patterns) {
    let firstPatternIndex = null;
    for (const pattern of patterns) {
        if (hasMatch(operation.text, pattern)) {
            firstPatternIndex = pattern.index;
            break;
        }
    }
    return {
        operationIndex: operation.operationIndex,
        kind: "match",
        firstPatternIndex,
    };
}
function processOperation(operation, patterns, redactionToken, outputs, budget) {
    if (operation.kind === "apply") {
        const applied = applyOperation(operation, patterns, redactionToken, outputs, budget);
        outputs.set(operation.operationIndex, applied.output);
        return applied.result;
    }
    if (operation.kind === "match")
        return matchResult(operation, patterns);
    return attachmentResult(operation, patterns, outputs, budget);
}
function validRequest(value) {
    return (isRecord(value) &&
        value.version === SECRET_REDACTION_WORKER_PROTOCOL_VERSION &&
        typeof value.requestId === "string" &&
        typeof value.redactionToken === "string" &&
        Array.isArray(value.patterns) &&
        Array.isArray(value.operations));
}
function processRequest(request) {
    if (request.redactionToken.length > 256) {
        throw new WorkerFailure("invalid_pattern");
    }
    const patterns = compilePatterns(request.patterns);
    if (request.operations.length > 8192) {
        throw new WorkerFailure("unexpected_failure");
    }
    const outputs = new Map();
    const budget = { matchSpans: 0, outputChars: 0 };
    const results = [];
    for (let index = 0; index < request.operations.length; index += 1) {
        const operation = request.operations[index];
        if (!operation ||
            operation.operationIndex !== index ||
            typeof operation.text !== "string") {
            throw new WorkerFailure("unexpected_failure");
        }
        results.push(processOperation(operation, patterns, request.redactionToken, outputs, budget));
    }
    return {
        version: SECRET_REDACTION_WORKER_PROTOCOL_VERSION,
        requestId: request.requestId,
        ok: true,
        results,
    };
}
function responseFor(request) {
    if (!validRequest(request)) {
        return {
            version: SECRET_REDACTION_WORKER_PROTOCOL_VERSION,
            requestId: "",
            ok: false,
            errorCode: "unexpected_failure",
        };
    }
    try {
        return processRequest(request);
    }
    catch (error) {
        return {
            version: SECRET_REDACTION_WORKER_PROTOCOL_VERSION,
            requestId: request.requestId,
            ok: false,
            errorCode: error instanceof WorkerFailure && error.code === "invalid_pattern"
                ? "invalid_pattern"
                : "unexpected_failure",
        };
    }
}
parentPort?.on("message", (request) => {
    parentPort?.postMessage(responseFor(request));
});
