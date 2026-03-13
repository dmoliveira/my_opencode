import type { GatewayHook } from "../registry.js";
interface GatewayClient {
    session?: {
        messages?(args: {
            path: {
                id: string;
            };
            query?: {
                directory?: string;
            };
        }): Promise<{
            data?: Array<{
                info?: {
                    role?: string;
                    error?: unknown;
                    time?: {
                        completed?: number;
                    };
                };
                parts?: Array<{
                    type?: string;
                    text?: string;
                    synthetic?: boolean;
                }>;
            }>;
        }>;
        promptAsync(args: {
            path: {
                id: string;
            };
            body: {
                parts: Array<{
                    type: string;
                    text: string;
                }>;
            };
            query?: {
                directory?: string;
            };
        }): Promise<void>;
    };
}
export declare function createLongTurnWatchdogHook(options: {
    directory: string;
    client?: GatewayClient;
    enabled: boolean;
    warningThresholdMs: number;
    toolCallWarningThreshold: number;
    reminderCooldownMs: number;
    maxSessionStateEntries: number;
    prefix: string;
    now?: () => number;
}): GatewayHook;
export {};
