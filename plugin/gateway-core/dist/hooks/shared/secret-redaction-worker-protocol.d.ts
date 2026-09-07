export declare const SECRET_REDACTION_WORKER_PROTOCOL_VERSION = 1;
export interface PatternWorkerPattern {
    index: number;
    source: string;
    flags: string;
}
export interface PatternWorkerSpan {
    start: number;
    end: number;
}
export interface PatternWorkerApplyOperation {
    operationIndex: number;
    kind: "apply";
    text: string;
    inputOperationIndex: number | null;
}
export interface PatternWorkerMatchOperation {
    operationIndex: number;
    kind: "match";
    text: string;
}
export interface PatternWorkerAttachmentOperation {
    operationIndex: number;
    kind: "attachment";
    text: string;
    payloadStart: number | null;
    payloadEnd: number | null;
    omittablePatternIndex: number | null;
    inputOperationIndex: number | null;
}
export type PatternWorkerOperation = PatternWorkerApplyOperation | PatternWorkerMatchOperation | PatternWorkerAttachmentOperation;
export interface PatternWorkerApplyStep {
    patternIndex: number;
    matches: PatternWorkerSpan[];
}
export interface PatternWorkerApplyResult {
    operationIndex: number;
    kind: "apply";
    inputLength: number;
    steps: PatternWorkerApplyStep[];
    firstPatternIndex: number | null;
    matchCount: number;
    positiveExpansion: number;
    residualPatternIndex: number | null;
    finalLength: number;
    finalSha256: string;
}
export interface PatternWorkerMatchResult {
    operationIndex: number;
    kind: "match";
    firstPatternIndex: number | null;
}
export interface PatternWorkerAttachmentResult {
    operationIndex: number;
    kind: "attachment";
    inputLength: number;
    blockingPatternIndex: number | null;
    matchSpanCount: number;
    omittedMatchCount: number;
}
export type PatternWorkerResult = PatternWorkerApplyResult | PatternWorkerMatchResult | PatternWorkerAttachmentResult;
export interface PatternWorkerRequest {
    version: number;
    requestId: string;
    redactionToken: string;
    patterns: PatternWorkerPattern[];
    operations: PatternWorkerOperation[];
}
export interface PatternWorkerSuccess {
    version: number;
    requestId: string;
    ok: true;
    results: PatternWorkerResult[];
}
export interface PatternWorkerFailure {
    version: number;
    requestId: string;
    ok: false;
    errorCode: "invalid_pattern" | "unexpected_failure";
}
export type PatternWorkerResponse = PatternWorkerSuccess | PatternWorkerFailure;
