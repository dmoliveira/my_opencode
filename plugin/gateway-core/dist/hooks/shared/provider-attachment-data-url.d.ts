export declare const MAX_OPAQUE_PNG_DATA_URL_CHARS: number;
export declare const MAX_OPAQUE_PNG_DECODED_BYTES: number;
export declare const MAX_OPAQUE_PNG_CHUNKS = 16384;
export declare const MAX_OPAQUE_PNG_DIMENSION = 32768;
export declare const MAX_OPAQUE_PNG_PIXELS = 100000000;
export declare function isStructurallyValidPngContainer(bytes: Buffer): boolean;
export declare function isCanonicalStructurallyValidPngDataUrl(value: string): boolean;
