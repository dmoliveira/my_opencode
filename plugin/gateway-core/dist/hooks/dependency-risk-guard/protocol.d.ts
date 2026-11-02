export declare const AUTH_REQUEST = "dependency-security authorize-uv-sync-locked";
export declare const SETUP_REQUEST = "uv sync --locked";
export declare const PENDING_MS = 180000;
export declare const PERMIT_MS = 60000;
export declare const MAX_STATE = 128;
export declare const METADATA_CHECK_REQUEST = "dependency-security check-uv-lock-virtual";
export declare const METADATA_MIGRATE_REQUEST = "dependency-security migrate-uv-lock-virtual";
export interface MetadataBinding extends Scope {
    phase: "check" | "migrate";
    issuer: string;
    nonce: string;
    original: string;
    candidate: string;
}
export interface MetadataPending extends MetadataBinding {
    command: string;
    until: number;
}
export interface MetadataFrame extends MetadataBinding {
    v: 1;
}
export interface MetadataInvocation extends MetadataBinding {
    v: 1;
    context: string;
    socket: string;
    capability: string;
}
/** Separate grammar: no metadata result can decode as an installation AuditFrame. */
export declare function parseMetadataFrame(output: unknown, expected: MetadataPending): MetadataFrame;
export declare function metadataFrame(binding: MetadataBinding): MetadataFrame;
export declare function encodeMetadataInvocation(value: MetadataInvocation): string;
export declare function decodeMetadataInvocation(encoded: string): MetadataInvocation;
/** Host-only metadata authority. Each attempt consumes synchronously, before any await. */
export declare class MetadataLedger {
    private readonly now;
    private pending;
    private permits;
    private seen;
    constructor(now?: () => number);
    clear(session?: string): void;
    sweep(): void;
    private reserve;
    begin(scope: Scope, original: string, command: (nonce: string) => string): MetadataPending;
    consume(scope: Scope): MetadataPending;
    finish(scope: Scope, command: unknown, exit: unknown, output: unknown): MetadataFrame | undefined;
}
export interface Scope {
    session: string;
    call: string;
    root: string;
    fingerprint: string;
}
export interface Pending extends Scope {
    nonce: string;
    command: string;
    until: number;
    auditorRoot?: string;
    auditorFingerprint?: string;
}
export interface AuditFrame {
    v: 1;
    nonce: string;
    fingerprint: string;
    packages: number;
    closure: string;
    auditor: "pip-audit==2.10.1";
    operation: "uv-sync-locked";
    build: "none";
    auditorRoot: string;
    auditorFingerprint: string;
}
/** Exactly one canonical frame: duplicate keys, chatter and truncated output fail closed. */
export declare function parseFrame(output: unknown, pending: Pending): AuditFrame;
/** Host-only, bounded and restart-ephemeral. All transitions are synchronous. */
export declare class AuthorizationLedger {
    private readonly now;
    private pending;
    private permits;
    private seen;
    constructor(now?: () => number);
    clear(session?: string): void;
    sweep(): void;
    begin(scope: Scope, command: (nonce: string) => string): Pending;
    finish(scope: Scope, command: unknown, exit: unknown, output: unknown, verifyAuditor?: (frame: AuditFrame) => void): boolean;
    consume(scope: Scope): Pending;
}
