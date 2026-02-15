interface GatewayEventPayload {
    event: {
        type: string;
        properties?: Record<string, unknown>;
    };
}
interface GatewayContext {
    config?: unknown;
}
export default function GatewayCorePlugin(ctx: GatewayContext): {
    event(input: GatewayEventPayload): Promise<void>;
};
export {};
