export interface GatewayHook {
    id: string;
    priority: number;
    /** Missing metadata preserves legacy dispatch to every event. */
    events?: readonly string[];
    event(type: string, payload: unknown): Promise<void>;
}
/** Selects hooks for an event while retaining legacy wildcard compatibility. */
export declare function hooksForEvent(hooks: GatewayHook[], eventType: string): GatewayHook[];
export declare function resolveHookOrder(hooks: GatewayHook[], order: string[], disabled: string[]): GatewayHook[];
