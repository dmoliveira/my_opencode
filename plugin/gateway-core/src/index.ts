import { loadGatewayConfig } from "./config/load.js"
import { createAutopilotLoopHook } from "./hooks/autopilot-loop/index.js"
import { createContinuationHook } from "./hooks/continuation/index.js"
import { createSafetyHook } from "./hooks/safety/index.js"
import { resolveHookOrder, type GatewayHook } from "./hooks/registry.js"

// Declares minimal plugin event payload shape for gateway dispatch.
interface GatewayEventPayload {
  event: {
    type: string
    properties?: Record<string, unknown>
  }
}

// Declares minimal context shape passed by plugin host.
interface GatewayContext {
  config?: unknown
}

// Creates ordered hook list using gateway config and default hooks.
function configuredHooks(rawConfig: unknown): GatewayHook[] {
  const cfg = loadGatewayConfig(rawConfig)
  const hooks = [createAutopilotLoopHook(), createContinuationHook(), createSafetyHook()]
  if (!cfg.hooks.enabled) {
    return []
  }
  return resolveHookOrder(hooks, cfg.hooks.order, cfg.hooks.disabled)
}

// Creates gateway plugin entrypoint with deterministic hook dispatch.
export default function GatewayCorePlugin(ctx: GatewayContext): {
  event(input: GatewayEventPayload): Promise<void>
} {
  const hooks = configuredHooks(ctx.config)

  // Dispatches plugin lifecycle event to all enabled hooks in order.
  async function event(input: GatewayEventPayload): Promise<void> {
    for (const hook of hooks) {
      await hook.event(input.event.type, input.event.properties)
    }
  }

  return { event }
}
