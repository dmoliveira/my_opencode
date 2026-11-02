import type { TaskerReadAuthority } from "./read-policy.js";
export declare function markTaskerResearchArgs(args: object): void;
export declare function isTaskerResearchArgs(args: unknown): boolean;
export declare const TASKER_RESEARCH_AGENTS: Set<string>;
export declare const TASKER_RESEARCH_CONSTRAINTS: readonly ["read-only", "no writes", "no Codememory", "no delegation", "no tests or builds", "no git or gh"];
export type TaskerResearchPacket = {
    objective: string;
    paths: string[];
    acceptance: string;
    checks: string;
    evidence: string;
    constraints: string[];
};
/** Free text never grants tools; descendants are separately restricted by ancestry. */
export declare function inspectResearchPacket(prompt: unknown): TaskerResearchPacket | null;
export declare function researchBoundary(packet: TaskerResearchPacket): string;
export type ResearchAuthority = TaskerReadAuthority & {
    parent: string;
    target: string;
    nonce: string;
    version: 1;
};
/** A child can reconstruct only the capability its native parent actually issued. */
export declare function createResearchAuthoritySigner(): {
    issue(capability: ResearchAuthority): string;
    verify(prompt: string, parent: string): ResearchAuthority | null;
};
