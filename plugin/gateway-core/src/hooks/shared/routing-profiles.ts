export const DEFAULT_ROUTING_CATEGORY = "balanced"

export interface RoutingProfile {
  description: string
  model: string
  temperature: number
  reasoning: string
  verbosity: string
}

export const ROUTING_PROFILES: Record<string, RoutingProfile> = {
  quick: {
    description: "Fast responses for routine operational tasks",
    model: "openai/gpt-5.4-mini",
    temperature: 0.1,
    reasoning: "low",
    verbosity: "low",
  },
  balanced: {
    description: "Default balanced profile for most engineering work",
    model: "openai/gpt-5.3-codex",
    temperature: 0.2,
    reasoning: "medium",
    verbosity: "medium",
  },
  deep: {
    description: "Higher-reliability analysis for complex engineering work",
    model: "openai/gpt-5.4-codex",
    temperature: 0.1,
    reasoning: "medium",
    verbosity: "medium",
  },
  critical: {
    description: "Critical-risk analysis and final safety review",
    model: "openai/gpt-5.4-codex",
    temperature: 0.0,
    reasoning: "medium",
    verbosity: "medium",
  },
  visual: {
    description: "UI/UX tasks with higher detail and output richness",
    model: "openai/gpt-5.3-codex",
    temperature: 0.2,
    reasoning: "medium",
    verbosity: "high",
  },
  writing: {
    description: "Documentation and communication with richer language style",
    model: "openai/gpt-5.3-codex",
    temperature: 0.6,
    reasoning: "medium",
    verbosity: "high",
  },
}

export const ROUTING_DOWNGRADE_CATEGORY: Record<string, string> = {
  critical: "balanced",
  deep: "balanced",
  balanced: "quick",
  quick: "",
  visual: "balanced",
  writing: "balanced",
}

export function normalizeRoutingCategory(value: unknown): string {
  return String(value ?? "").trim().toLowerCase()
}

export function normalizeModelRef(providerID: string | undefined, modelID: string | undefined): string {
  const provider = typeof providerID === "string" ? providerID.trim() : ""
  const model = typeof modelID === "string" ? modelID.trim() : ""
  if (!provider || !model) {
    return ""
  }
  return `${provider}/${model}`
}

export function normalizeModelName(value: unknown): string {
  return String(value ?? "").trim()
}

export function routingProfileForCategory(value: unknown): RoutingProfile | null {
  const category = normalizeRoutingCategory(value)
  return ROUTING_PROFILES[category] ?? null
}

export function routingModelForCategory(value: unknown): string {
  return routingProfileForCategory(value)?.model ?? ""
}

export function routingCategoryForModel(model: unknown): string {
  const normalized = normalizeModelName(model)
  if (!normalized) {
    return ""
  }
  for (const [category, profile] of Object.entries(ROUTING_PROFILES)) {
    if (profile.model === normalized) {
      return category
    }
  }
  return ""
}

export function downgradeRoutingCategory(category: unknown): string {
  const normalized = normalizeRoutingCategory(category)
  return ROUTING_DOWNGRADE_CATEGORY[normalized] ?? ""
}

export function downgradeRoutingModel(model: unknown, preferredCategory?: unknown): string {
  const preferred = normalizeRoutingCategory(preferredCategory)
  const category = preferred || routingCategoryForModel(model)
  const nextCategory = downgradeRoutingCategory(category)
  return routingModelForCategory(nextCategory)
}

export function defaultRoutingSystemSettings(): Pick<RoutingProfile, "model" | "temperature" | "reasoning" | "verbosity"> {
  const profile = ROUTING_PROFILES[DEFAULT_ROUTING_CATEGORY]
  return {
    model: profile.model,
    temperature: profile.temperature,
    reasoning: profile.reasoning,
    verbosity: profile.verbosity,
  }
}
