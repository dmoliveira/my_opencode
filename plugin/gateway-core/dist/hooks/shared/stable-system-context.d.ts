export declare const RUNTIME_SESSION_CONTEXT_MARKER = "runtime_session_context:";
export declare const RUNTIME_CONCISE_CONTEXT_MARKER = "runtime_concise_mode:";
export declare function managedRuntimeSystemMarker(entry: string): string | null;
export declare function insertStableSystemContext(system: string[], context: string): void;
export declare function stableContextLabel(value: string): string;
