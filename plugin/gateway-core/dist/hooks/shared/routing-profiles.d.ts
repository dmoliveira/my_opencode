export interface RoutingProfile {
    description: string;
    model: string;
    temperature: number;
    reasoning: string;
    verbosity: string;
}
export declare const DEFAULT_ROUTING_CATEGORY: string;
export declare const ROUTING_PROFILES: Record<string, RoutingProfile>;
export declare const ROUTING_DOWNGRADE_CATEGORY: Record<string, string>;
export declare function normalizeRoutingCategory(value: unknown): string;
export declare function normalizeModelRef(providerID: string | undefined, modelID: string | undefined): string;
export declare function normalizeModelName(value: unknown): string;
export declare function routingProfileForCategory(value: unknown): RoutingProfile | null;
export declare function routingModelForCategory(value: unknown): string;
export declare function routingCategoryForModel(model: unknown): string;
export declare function downgradeRoutingCategory(category: unknown): string;
export declare function downgradeRoutingModel(model: unknown, preferredCategory?: unknown): string;
export declare function defaultRoutingSystemSettings(): Pick<RoutingProfile, "model" | "temperature" | "reasoning" | "verbosity">;
