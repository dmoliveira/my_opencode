import type { GatewayHook } from "../registry.js"

// Creates safety guard hook placeholder for gateway composition.
export function createSafetyHook(): GatewayHook {
  return {
    id: "safety",
    priority: 300,
    async event(_type: string, _payload: unknown): Promise<void> {
      return
    },
  }
}
