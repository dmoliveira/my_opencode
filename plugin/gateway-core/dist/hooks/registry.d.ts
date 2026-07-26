export interface GatewayHook {
    id: string;
    priority: number;
    /** Missing metadata preserves legacy dispatch to every event. */
    events?: readonly string[];
    event(type: string, payload: unknown): Promise<void>;
}
export interface HookDependencyBlock {
    hookId: string;
    dependencyId: string;
}
export interface HookConstructionPlan {
    order: string[];
    selected: ReadonlySet<string> | null;
    blocked: HookDependencyBlock[];
}
/** Expands omitted stateful dependencies and excludes unsafe consumers. */
export declare function resolveHookConstructionPlan(order: string[], disabled: string[]): HookConstructionPlan;
/** Selects hooks for an event while retaining legacy wildcard compatibility. */
export declare function hooksForEvent(hooks: GatewayHook[], eventType: string): GatewayHook[];
export declare function resolveHookOrder(hooks: GatewayHook[], order: string[], disabled: string[]): GatewayHook[];
