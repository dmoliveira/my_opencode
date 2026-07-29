export declare const OPAQUE_PROVIDER_ATTACHMENT_MIME_TYPES: readonly ["image/png", "image/jpeg", "application/pdf"];
export type OpaqueProviderAttachmentMime = (typeof OPAQUE_PROVIDER_ATTACHMENT_MIME_TYPES)[number];
export interface CanonicalProviderAttachmentDataUrl {
    mime: OpaqueProviderAttachmentMime;
    payloadStart: number;
    payloadEnd: number;
    decodedBytes: number;
}
export declare const MAX_OPAQUE_ATTACHMENT_DATA_URL_CHARS: number;
export declare const MAX_OPAQUE_ATTACHMENT_DECODED_BYTES: number;
export declare const MAX_OPAQUE_PNG_DATA_URL_CHARS: number;
export declare const MAX_OPAQUE_PNG_DECODED_BYTES: number;
export declare const MAX_OPAQUE_PNG_CHUNKS = 16384;
export declare const MAX_OPAQUE_PNG_DIMENSION = 32768;
export declare const MAX_OPAQUE_PNG_PIXELS = 100000000;
export declare function isStructurallyValidPngContainer(bytes: Buffer): boolean;
export declare function parseCanonicalProviderAttachmentDataUrl(value: string, expectedMime: string): CanonicalProviderAttachmentDataUrl | null;
export declare function isCanonicalStructurallyValidPngDataUrl(value: string): boolean;
