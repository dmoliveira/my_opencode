import type { ToolHooks } from "./types.js";
type DirectoryResolver = (sessionID: string) => Promise<string>;
/**
 * Port only the two shell-command guards. This is intentionally not a V2
 * gateway entrypoint: edit, delegation and other safety hooks need their own
 * adapters and tests before the gateway can be declared active.
 */
export declare function registerV2ShellGuards(tool: ToolHooks, resolveDirectory: DirectoryResolver, options: {
    directory: string;
    noninteractive: {
        enabled: boolean;
        injectEnvPrefix: boolean;
        envPrefixes: string[];
        prefixCommands: string[];
        blockedPatterns: string[];
    };
    dangerous: {
        enabled: boolean;
        blockedPatterns: string[];
    };
}): Promise<() => Promise<void>>;
export {};
