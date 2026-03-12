export type ToolAfterOutputChannel = "string" | "stdout" | "output" | "message" | "stderr" | "unknown";
export interface ToolAfterOutputEntry {
    channel: ToolAfterOutputChannel;
    text: string;
}
export declare function listToolAfterOutputTexts(output: unknown): ToolAfterOutputEntry[];
export declare function inspectToolAfterOutputText(output: unknown): {
    text: string;
    channel: ToolAfterOutputChannel;
};
export declare function readToolAfterOutputText(output: unknown): string;
export declare function readCombinedToolAfterOutputText(output: unknown): string;
export declare function writeToolAfterOutputChannelText(output: unknown, channel: ToolAfterOutputChannel, text: string): boolean;
export declare function writeToolAfterOutputText(output: unknown, text: string, preferredChannel?: ToolAfterOutputChannel): boolean;
