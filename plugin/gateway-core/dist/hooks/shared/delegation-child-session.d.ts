interface SessionInfoLike {
    id?: string;
    parentID?: string;
    title?: string;
}
interface SessionCreatedLike {
    properties?: {
        info?: SessionInfoLike;
    };
}
export interface DelegationChildSessionLink {
    childSessionId: string;
    parentSessionId: string;
    traceId?: string;
}
export declare function registerDelegationChildSession(payload: SessionCreatedLike): DelegationChildSessionLink | null;
export declare function getDelegationChildSessionLink(childSessionId: string): DelegationChildSessionLink | null;
export declare function clearDelegationChildSessionLink(childSessionId: string): DelegationChildSessionLink | null;
export {};
