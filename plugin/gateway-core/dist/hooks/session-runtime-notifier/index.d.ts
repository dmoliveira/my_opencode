import type { GatewayHook } from "../registry.js";
interface ToastClient {
    showToast(args?: {
        title?: string;
        message?: string;
        variant?: "info" | "success" | "warning" | "error";
        duration?: number;
        directory?: string;
        workspace?: string;
    }): Promise<unknown>;
}
export declare function createSessionRuntimeNotifierHook(options: {
    directory: string;
    enabled: boolean;
    durationMs: number;
    client?: {
        tui?: ToastClient;
    };
}): GatewayHook;
export {};
