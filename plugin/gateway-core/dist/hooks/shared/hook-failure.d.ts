export declare const CRITICAL_GATEWAY_HOOK_IDS: Set<string>;
export declare function isCriticalGatewayHookId(hookId: string): boolean;
export declare function describeHookFailure(error: unknown): string;
export declare function isIntentionalHookBlock(error: unknown): boolean;
export declare function surfaceGatewayHookFailure(message: string): void;
export declare function normalizeHookError(error: unknown, fallback: string): Error;
