export declare const RUNNER: string;
export declare const ENV: Readonly<{
    PATH: "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin";
    LANG: "C.UTF-8";
    LC_ALL: "C.UTF-8";
    UV_PYTHON_DOWNLOADS: "never";
    PYTHONDONTWRITEBYTECODE: "1";
}>;
export declare function digest(value: string | Buffer): string;
/** Reject aliases, hardlinks, special files and symlink ancestors before opening. */
export declare function safeRead(path: string, limit?: number): Buffer;
export declare function exists(path: string): boolean;
export declare function run(executable: string, args: string[], cwd: string, timeout?: number, environment?: Record<string, string>): string;
export interface FileIdentity {
    path: string;
    sha256: string;
}
export interface DirectoryIdentity {
    path: string;
    dev: string;
    ino: string;
}
interface MarkerIdentity extends DirectoryIdentity {
    kind: "file" | "directory";
    sha256: string;
}
declare const EXECUTABLES: readonly ["node", "git", "uv", "python"];
declare const DIRECTORIES: readonly ["root", "cache", "git"];
declare const POLICY = "virtual-wheel-only-v3";
export interface Snapshot {
    v: 1;
    policy: typeof POLICY;
    root: string;
    fingerprint: string;
    node: string;
    git: string;
    uv: string;
    python: string;
    cache: string;
    version: string;
    inputs: Record<string, string>;
    executables: Record<typeof EXECUTABLES[number], FileIdentity>;
    helpers: FileIdentity[];
    directories: Record<typeof DIRECTORIES[number], DirectoryIdentity>;
    marker: MarkerIdentity;
    absent: string[];
}
/** Fixed tuple order, never arbitrary caller-controlled object ordering. */
export declare function snapshotFingerprint(s: Omit<Snapshot, "fingerprint"> | Snapshot): string;
export declare function encodeSnapshot(snapshot: Snapshot): string;
export declare function decodeSnapshot(encoded: string): Snapshot;
export declare function directoryIdentity(path: string): DirectoryIdentity;
/** Pure continuity check: never execute Git, UV, Python, Node or scanner code. */
export declare function recapture(snapshot: Snapshot): Snapshot;
export declare function validateProject(project: Record<string, unknown>, lock: Record<string, unknown>): void;
export declare function capture(directory: string): Snapshot;
export interface Auditor {
    root: string;
    fingerprint: string;
    python: string;
    libraries: string[];
}
/** Non-executing verification: changed auditor code must not run before rejection. */
export declare function captureAuditor(root: string, snapshot: Snapshot): Auditor;
/** Only the normal Bash runner calls this; offline fixed-tool discovery has no project inputs. */
export declare function discoverAuditor(snapshot: Snapshot, subprocess?: typeof run): Auditor;
export declare function quote(value: string): string;
export declare function runnerCommand(snapshot: Snapshot, mode: "audit" | "setup", nonce: string, socket?: string, auditorRoot?: string, auditorFingerprint?: string): string;
export {};
