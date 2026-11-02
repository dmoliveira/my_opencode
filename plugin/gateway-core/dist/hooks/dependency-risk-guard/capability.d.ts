import type { MetadataBinding } from "./protocol.js";
export interface Capability {
    path: string;
    nonce: string;
    until: number;
    close: () => void;
}
/** Private, one-shot host handshake. A CLI flag/receipt cannot mint a setup permit. */
export declare function capability(fingerprint: string, recheck: () => void): Promise<Capability>;
export declare function metadataCapabilityBinding(binding: MetadataBinding): string;
export declare function metadataCapability(binding: MetadataBinding, recheck: () => void): Promise<Capability>;
