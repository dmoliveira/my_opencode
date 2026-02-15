// Declares completion mode options for gateway autopilot loop.
export type CompletionMode = "promise" | "objective"

// Declares ordered quality profile levels.
export type QualityProfile = "off" | "fast" | "strict"

// Declares loop-related configuration knobs.
export interface AutopilotLoopConfig {
  enabled: boolean
  maxIterations: number
  orphanMaxAgeHours: number
  completionMode: CompletionMode
  completionPromise: string
}

// Declares quality toggle settings for plugin-side checks.
export interface QualityConfig {
  profile: QualityProfile
  ts: {
    lint: boolean
    typecheck: boolean
    tests: boolean
  }
  py: {
    selftest: boolean
  }
}

// Declares top-level gateway plugin configuration.
export interface GatewayConfig {
  hooks: {
    enabled: boolean
    disabled: string[]
    order: string[]
  }
  autopilotLoop: AutopilotLoopConfig
  quality: QualityConfig
}

// Defines safe gateway defaults for production usage.
export const DEFAULT_GATEWAY_CONFIG: GatewayConfig = {
  hooks: {
    enabled: true,
    disabled: [],
    order: ["autopilot-loop", "continuation", "safety"],
  },
  autopilotLoop: {
    enabled: true,
    maxIterations: 0,
    orphanMaxAgeHours: 12,
    completionMode: "promise",
    completionPromise: "DONE",
  },
  quality: {
    profile: "fast",
    ts: {
      lint: true,
      typecheck: true,
      tests: false,
    },
    py: {
      selftest: true,
    },
  },
}
