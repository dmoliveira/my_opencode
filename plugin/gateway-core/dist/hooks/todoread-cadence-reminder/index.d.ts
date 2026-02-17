import type { GatewayHook } from "../registry.js";
export declare function createTodoreadCadenceReminderHook(options: {
    enabled: boolean;
    cooldownEvents: number;
}): GatewayHook;
