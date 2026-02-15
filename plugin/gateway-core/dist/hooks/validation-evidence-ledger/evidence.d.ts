export type ValidationEvidenceCategory = "lint" | "test" | "typecheck" | "build" | "security";
export interface ValidationEvidenceSnapshot {
    lint: boolean;
    test: boolean;
    typecheck: boolean;
    build: boolean;
    security: boolean;
    updatedAt: string;
}
export declare function markerCategory(marker: string): ValidationEvidenceCategory | null;
export declare function validationEvidence(sessionId: string): ValidationEvidenceSnapshot;
export declare function markValidationEvidence(sessionId: string, categories: ValidationEvidenceCategory[]): ValidationEvidenceSnapshot;
export declare function clearValidationEvidence(sessionId: string): void;
export declare function missingValidationMarkers(sessionId: string, markers: string[]): string[];
