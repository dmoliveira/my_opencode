interface TraceArgs {
    [key: string]: unknown;
    prompt?: string;
    description?: string;
    subagent_type?: string;
    category?: string;
}
interface DelegationMetadataCarrier {
    metadata?: unknown;
}
export declare function resolveDelegationTraceId(args: TraceArgs): string;
export declare function annotateDelegationMetadata(carrier: DelegationMetadataCarrier, args: TraceArgs | undefined): void;
export declare function extractDelegationTraceId(args: TraceArgs | undefined, metadata?: unknown): string;
export declare function extractDelegationSubagentType(args: TraceArgs | undefined, metadata?: unknown): string;
export declare function extractDelegationCategory(args: TraceArgs | undefined, metadata?: unknown): string;
export declare function extractDelegationSubagentTypeFromOutput(output: string): string;
export {};
