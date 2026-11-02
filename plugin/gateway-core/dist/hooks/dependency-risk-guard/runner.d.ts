import { recapture, captureAuditor, discoverAuditor, run, type Snapshot, type Auditor } from "./safety.js";
import type { AuditFrame } from "./protocol.js";
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
/** Every setup repeats the real audit; no receipt or supplied package list is accepted. */
export declare function execute(mode: string, root: string, nonce: string, fingerprint: string, socket: string, auditorRoot?: string, auditorFingerprint?: string, boundSnapshot?: Snapshot | undefined, boundary?: {
    inspect: typeof recapture;
    subprocess: typeof run;
    auditor: typeof discoverAuditor;
    inspectAuditor: typeof captureAuditor;
}): Promise<AuditFrame>;
