interface ToolArgs {
    workdir?: string;
    cwd?: string;
    filePath?: string;
    path?: string;
    file_path?: string;
}
interface ToolPayload {
    output?: {
        args?: ToolArgs;
    };
    directory?: string;
}
export declare function effectiveToolDirectory(payload: ToolPayload, fallbackDirectory: string): string;
export {};
