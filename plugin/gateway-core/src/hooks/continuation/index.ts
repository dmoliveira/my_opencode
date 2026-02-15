import type { GatewayHook } from "../registry.js"

// Creates continuation helper hook placeholder for gateway composition.
export function createContinuationHook(): GatewayHook {
  return {
    id: "continuation",
    priority: 200,
    async event(_type: string, _payload: unknown): Promise<void> {
      return
    },
  }
}
