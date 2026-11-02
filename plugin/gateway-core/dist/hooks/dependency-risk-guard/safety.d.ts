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
export declare const METADATA_POLICY = "read-only-editable-dot-metadata-v1";
export interface Snapshot {
    v: 1;
    policy: typeof POLICY | typeof METADATA_POLICY;
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
/** Informational policy only: never accepted by audit/setup or scanner discovery. */
export declare function validateMetadataProject(project: Record<string, unknown>, lock: Record<string, unknown>): void;
/** Conservative byte edit; trusted TOML proof is separately required before UV runs. */
export declare function metadataCandidate(original: Buffer): {
    candidate: Buffer;
    start: number;
    end: number;
};
/** Both strict parsed documents must agree outside the single matching root source. */
export declare function proveMetadataConversion(project: Record<string, unknown>, original: Buffer, candidate: Buffer, lock: Record<string, unknown>, converted: Record<string, unknown>): void;
export declare function capture(directory: string): Snapshot;
export declare function captureMetadata(directory: string): Snapshot;
export interface MetadataFile extends DirectoryIdentity {
    uid: string;
    mode: number;
    size: number;
    sha256: string;
}
export interface MetadataContext {
    v: 1;
    policy: "one-key-metadata-promotion-v1";
    snapshot: Snapshot;
    original: MetadataFile;
    common: DirectoryIdentity;
    pointer: {
        kind: "absent";
    } | {
        kind: "file";
        file: MetadataFile;
        target: string;
    };
    fingerprint: string;
}
/** Identity plus bytes; timestamps deliberately are not authority fields. */
export declare function metadataFile(path: string): MetadataFile;
export declare function metadataFingerprint(context: Omit<MetadataContext, "fingerprint"> | MetadataContext): string;
export declare function encodeMetadataContext(context: MetadataContext): string;
export declare function decodeMetadataContext(encoded: string): MetadataContext;
export declare function captureMetadataContext(directory: string): MetadataContext;
export declare function recaptureMetadataContext(context: MetadataContext): MetadataContext;
/** The sole permitted post-state: this prepared inode, not identical replacement bytes. */
export declare function verifyMetadataTransition(context: MetadataContext, prepared: MetadataFile, candidateHash: string): void;
export interface MetadataPreparation {
    namespace: DirectoryIdentity;
    job: DirectoryIdentity;
    backup: MetadataFile;
    candidate: MetadataFile;
    descriptors: number[];
}
export declare function metadataPaths(context: MetadataContext, nonce: string): {
    namespace: string;
    job: string;
    backup: string;
    candidate: string;
};
/** Called independently by the helper and live host callback, with no caller paths. */
export declare function inspectMetadataPreparation(context: MetadataContext, nonce: string, candidateHash: string): MetadataPreparation;
export declare function verifyMetadataPreparation(context: MetadataContext, nonce: string, candidateHash: string, prepared: MetadataPreparation): void;
export declare function closeMetadataPreparation(prepared: MetadataPreparation, cleanup?: boolean): void;
export declare function verifyMetadataRecovery(prepared: MetadataPreparation): void;
export declare function prepareMetadata(context: MetadataContext, nonce: string, expected: string): MetadataPreparation;
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
