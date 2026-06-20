import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

export interface RoutingProfile {
  description: string
  model: string
  temperature: number
  reasoning: string
  verbosity: string
}

interface RoutingProfilesData {
  default_category: string
  profiles: Record<string, RoutingProfile>
  downgrade_category: Record<string, string>
}

function loadRoutingProfilesData(): RoutingProfilesData {
  const moduleDir = dirname(fileURLToPath(import.meta.url))
  const packageRoot = join(moduleDir, "..", "..", "..")
  const dataPath = join(packageRoot, "routing-profiles.data.json")
  return JSON.parse(readFileSync(dataPath, "utf-8")) as RoutingProfilesData
}

const ROUTING_PROFILES_DATA = loadRoutingProfilesData()

export const DEFAULT_ROUTING_CATEGORY = ROUTING_PROFILES_DATA.default_category

export const ROUTING_PROFILES: Record<string, RoutingProfile> = ROUTING_PROFILES_DATA.profiles

export const ROUTING_DOWNGRADE_CATEGORY: Record<string, string> =
  ROUTING_PROFILES_DATA.downgrade_category

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
