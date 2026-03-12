export type ValidationEvidenceCategory = "lint" | "test" | "typecheck" | "build" | "security";
export type ValidationEvidenceSource = "session" | "worktree" | "session+worktree" | "none";
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
export declare function worktreeValidationEvidence(directory: string): ValidationEvidenceSnapshot;
export declare function markValidationEvidence(sessionId: string, categories: ValidationEvidenceCategory[], directory?: string): ValidationEvidenceSnapshot;
export declare function clearValidationEvidence(sessionId: string): void;
export declare function missingValidationMarkers(sessionId: string, markers: string[]): string[];
export declare function validationEvidenceStatus(sessionId: string, markers: string[], directory?: string): {
    missing: string[];
    source: ValidationEvidenceSource;
};
