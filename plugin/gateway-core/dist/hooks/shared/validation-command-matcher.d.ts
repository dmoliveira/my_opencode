import type { ValidationEvidenceCategory } from "../validation-evidence-ledger/evidence.js";
export declare function validationCommandDirectory(command: string, fallback: string): string;
export declare function classifyValidationCommand(command: string): ValidationEvidenceCategory[];
export declare function isValidationCommand(command: string): boolean;
