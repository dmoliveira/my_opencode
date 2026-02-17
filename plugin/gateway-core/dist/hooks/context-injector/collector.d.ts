interface ContextEntry {
    id: string;
    source: string;
    content: string;
    priority: "critical" | "high" | "normal" | "low";
    timestamp: number;
}
export declare class ContextCollector {
    private sessions;
    private keyFor;
    register(sessionId: string, options: {
        source: string;
        id?: string;
        content: string;
        priority?: ContextEntry["priority"];
    }): void;
    hasPending(sessionId: string): boolean;
    consume(sessionId: string): {
        hasContent: boolean;
        merged: string;
    };
    clear(sessionId: string): void;
}
export declare const contextCollector: ContextCollector;
export {};
