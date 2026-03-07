interface TraceArgs {
    [key: string]: unknown;
    prompt?: string;
    description?: string;
}
export declare function resolveDelegationTraceId(args: TraceArgs): string;
export {};
