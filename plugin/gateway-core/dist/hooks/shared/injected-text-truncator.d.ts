export declare const DEFAULT_INJECTED_TEXT_MAX_CHARS = 12000;
export interface TruncatedTextResult {
    text: string;
    truncated: boolean;
    originalLength: number;
}
export declare function truncateInjectedText(text: string, maxChars: number): TruncatedTextResult;
