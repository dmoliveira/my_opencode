import { renameSync } from "node:fs";
import { recapture, captureAuditor, discoverAuditor, run, METADATA_POLICY, type Snapshot, type Auditor, type FileIdentity } from "./safety.js";
import type { AuditFrame } from "./protocol.js";
import { type MetadataInvocation, type MetadataFrame } from "./protocol.js";
export interface Requirement {
    name: string;
    version: string;
    hashes: string[];
}
/** No URLs, includes, arbitrary options or extras. Markers require trusted host evaluation. */
export declare function requirements(text: string, evaluate?: (marker: string) => boolean, collecting?: boolean): Requirement[];
export declare function hostRequirements(text: string, snapshot: Snapshot, auditor: Auditor, subprocess: typeof run): Requirement[];
export declare function samePackages(actual: unknown, expected: Requirement[]): void;
export declare function validateAudit(text: string, expected: Requirement[]): void;
/** Informational consistency check only. No AuditFrame, scanner, capability or installer. */
export declare function checkMetadata(snapshot: Snapshot, sentinels?: readonly FileIdentity[], boundary?: {
    inspect: typeof recapture;
    subprocess: typeof run;
}): {
    policy: typeof METADATA_POLICY;
    fingerprint: string;
    original: string;
    candidate: string;
    start: number;
    end: number;
    commands: {
        executable: string;
        args: string[];
    }[];
    sentinels: readonly FileIdentity[];
};
declare function redeem(socket: string, nonce: string, fingerprint: string, metadata?: boolean): Promise<void>;
/** Dedicated CLI/authority domain; the read-only checker remains the only subprocess path. */
export declare function executeMetadata(invocation: MetadataInvocation, boundary?: {
    check: typeof checkMetadata;
    redeem: typeof redeem;
    rename: typeof renameSync;
}): Promise<MetadataFrame>;
/** Every setup repeats the real audit; no receipt or supplied package list is accepted. */
export declare function execute(mode: string, root: string, nonce: string, fingerprint: string, socket: string, auditorRoot?: string, auditorFingerprint?: string, boundSnapshot?: Snapshot | undefined, boundary?: {
    inspect: typeof recapture;
    subprocess: typeof run;
    auditor: typeof discoverAuditor;
    inspectAuditor: typeof captureAuditor;
}): Promise<AuditFrame>;
export {};
