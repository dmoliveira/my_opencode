export interface PrBodyInspection {
    body: string;
    inspectable: boolean;
}
export declare function tokenizeShellCommand(command: string): string[];
export declare function isGitHubPrMergeCommand(command: string): boolean;
export declare function extractGitHubPrMergeSelector(command: string): string;
export declare function gitHubPrMergeHasStrategy(command: string): boolean;
export declare function isGitHubPrCreateCommand(command: string): boolean;
export declare function inspectGitHubPrCreateBody(command: string, directory: string): PrBodyInspection;
