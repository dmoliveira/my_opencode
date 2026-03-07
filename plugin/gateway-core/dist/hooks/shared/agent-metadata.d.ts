export interface AgentRoutingMetadata {
    cost_tier?: string;
    default_category?: string;
    fallback_policy?: string;
    triggers?: string[];
    avoid_when?: string[];
    denied_tools?: string[];
}
export declare function loadAgentMetadata(directory: string): Map<string, AgentRoutingMetadata>;
