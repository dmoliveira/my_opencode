export interface GatewayHook {
    id: string;
    priority: number;
    event(type: string, payload: unknown): Promise<void>;
}
export declare function resolveHookOrder(hooks: GatewayHook[], order: string[], disabled: string[]): GatewayHook[];
