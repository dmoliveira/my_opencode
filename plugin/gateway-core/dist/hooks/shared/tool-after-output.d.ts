export type ToolAfterOutputChannel = "string" | "stdout" | "output" | "message" | "stderr" | "unknown";
export declare function inspectToolAfterOutputText(output: unknown): {
    text: string;
    channel: ToolAfterOutputChannel;
};
export declare function readToolAfterOutputText(output: unknown): string;
export declare function writeToolAfterOutputText(output: unknown, text: string, preferredChannel?: ToolAfterOutputChannel): boolean;
