declare const FINGERPRINT_VERSION: "git-state-v1";
export interface GitStateFingerprint {
    version: typeof FINGERPRINT_VERSION;
    root: string;
    head: string;
    index: string;
    worktree: string;
    digest: string;
}
export declare function captureGitStateFingerprint(directory: string): GitStateFingerprint | null;
export declare function sameGitState(left: GitStateFingerprint | null | undefined, right: GitStateFingerprint | null | undefined): boolean;
export {};
