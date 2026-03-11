interface SessionInfoLike {
    id?: string;
    parentID?: string;
    title?: string;
    metadata?: unknown;
}
interface SessionCreatedLike {
    properties?: {
        info?: SessionInfoLike;
    };
}
export interface DelegationChildSessionLink {
    childSessionId: string;
    parentSessionId: string;
    childRunId?: string;
    traceId?: string;
    subagentType?: string;
}
export declare function registerDelegationChildSession(payload: SessionCreatedLike): DelegationChildSessionLink | null;
export declare function getDelegationChildSessionLink(childSessionId: string): DelegationChildSessionLink | null;
export declare function clearDelegationChildSessionLink(childSessionId: string): DelegationChildSessionLink | null;
export {};
