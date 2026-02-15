import { DEFAULT_GATEWAY_CONFIG, type GatewayConfig } from "./schema.js"

// Coerces unknown value into a normalized string array.
function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

// Coerces unknown value into a safe non-negative integer fallback.
function nonNegativeInt(value: unknown, fallback: number): number {
  const parsed = Number.parseInt(String(value ?? ""), 10)
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallback
  }
  return parsed
}

// Loads and normalizes gateway plugin config from unknown input.
export function loadGatewayConfig(raw: unknown): GatewayConfig {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {}
  const hooksSource =
    source.hooks && typeof source.hooks === "object"
      ? (source.hooks as Record<string, unknown>)
      : {}
  const autopilotSource =
    source.autopilotLoop && typeof source.autopilotLoop === "object"
      ? (source.autopilotLoop as Record<string, unknown>)
      : {}
  const qualitySource =
    source.quality && typeof source.quality === "object"
      ? (source.quality as Record<string, unknown>)
      : {}
  const tsSource =
    qualitySource.ts && typeof qualitySource.ts === "object"
      ? (qualitySource.ts as Record<string, unknown>)
      : {}
  const pySource =
    qualitySource.py && typeof qualitySource.py === "object"
      ? (qualitySource.py as Record<string, unknown>)
      : {}

  const completionMode =
    autopilotSource.completionMode === "objective" ? "objective" : "promise"
  const qualityProfile =
    qualitySource.profile === "off" || qualitySource.profile === "strict"
      ? qualitySource.profile
      : "fast"

  return {
    hooks: {
      enabled:
        typeof hooksSource.enabled === "boolean"
          ? hooksSource.enabled
          : DEFAULT_GATEWAY_CONFIG.hooks.enabled,
      disabled: stringList(hooksSource.disabled),
      order: stringList(hooksSource.order),
    },
    autopilotLoop: {
      enabled:
        typeof autopilotSource.enabled === "boolean"
          ? autopilotSource.enabled
          : DEFAULT_GATEWAY_CONFIG.autopilotLoop.enabled,
      maxIterations: nonNegativeInt(
        autopilotSource.maxIterations,
        DEFAULT_GATEWAY_CONFIG.autopilotLoop.maxIterations,
      ),
      orphanMaxAgeHours: nonNegativeInt(
        autopilotSource.orphanMaxAgeHours,
        DEFAULT_GATEWAY_CONFIG.autopilotLoop.orphanMaxAgeHours,
      ),
      completionMode,
      completionPromise:
        typeof autopilotSource.completionPromise === "string" &&
        autopilotSource.completionPromise.trim().length > 0
          ? autopilotSource.completionPromise.trim()
          : DEFAULT_GATEWAY_CONFIG.autopilotLoop.completionPromise,
    },
    quality: {
      profile: qualityProfile,
      ts: {
        lint: typeof tsSource.lint === "boolean" ? tsSource.lint : true,
        typecheck: typeof tsSource.typecheck === "boolean" ? tsSource.typecheck : true,
        tests: typeof tsSource.tests === "boolean" ? tsSource.tests : false,
      },
      py: {
        selftest: typeof pySource.selftest === "boolean" ? pySource.selftest : true,
      },
    },
  }
}
