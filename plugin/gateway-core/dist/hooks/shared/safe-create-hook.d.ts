export declare function safeCreateHook<T>(input: {
    directory: string;
    hookId: string;
    factory: () => T;
}): T | null;
