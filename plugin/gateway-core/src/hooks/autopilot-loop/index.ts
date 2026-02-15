import type { GatewayHook } from "../registry.js"

// Creates autopilot loop hook placeholder for gateway composition.
export function createAutopilotLoopHook(): GatewayHook {
  return {
    id: "autopilot-loop",
    priority: 100,
    async event(_type: string, _payload: unknown): Promise<void> {
      return
    },
  }
}
