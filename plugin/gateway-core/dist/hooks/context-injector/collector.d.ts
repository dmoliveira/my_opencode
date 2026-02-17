interface ContextEntry {
    id: string;
    source: string;
    content: string;
    priority: "critical" | "high" | "normal" | "low";
    timestamp: number;
    metadata?: Record<string, unknown>;
}
interface RegisterContextOptions {
    source: string;
    id?: string;
    content: string;
    priority?: ContextEntry["priority"];
    metadata?: Record<string, unknown>;
}
interface PendingContext {
    hasContent: boolean;
    merged: string;
    entries: ContextEntry[];
}
export declare class ContextCollector {
    private sessions;
    private keyFor;
    register(sessionId: string, options: RegisterContextOptions): void;
    hasPending(sessionId: string): boolean;
    getPending(sessionId: string): PendingContext;
    consume(sessionId: string): PendingContext;
    clear(sessionId: string): void;
    private sortEntries;
}
export declare const contextCollector: ContextCollector;
export {};
