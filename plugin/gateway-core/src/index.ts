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
  directory?: string
  client?: {
    session?: {
      messages(args: {
        path: { id: string }
        query?: { directory?: string }
      }): Promise<{
        data?: Array<{ info?: { role?: string }; parts?: Array<{ type: string; text?: string }> }>
      }>
      promptAsync(args: {
        path: { id: string }
        body: { parts: Array<{ type: string; text: string }> }
        query?: { directory?: string }
      }): Promise<void>
    }
  }
}

// Declares minimal slash command pre-execution input shape.
interface ToolBeforeInput {
  tool: string
  sessionID?: string
}

// Declares minimal slash command mutable output shape.
interface ToolBeforeOutput {
  args?: { command?: string }
}

// Declares minimal chat message event input shape.
interface ChatMessageInput {
  sessionID?: string
}

// Creates ordered hook list using gateway config and default hooks.
function configuredHooks(ctx: GatewayContext): GatewayHook[] {
  const directory = typeof ctx.directory === "string" && ctx.directory.trim() ? ctx.directory : process.cwd()
  const cfg = loadGatewayConfig(ctx.config)
  const hooks = [
    createAutopilotLoopHook({
      directory,
      defaults: {
        enabled: cfg.autopilotLoop.enabled,
        maxIterations: cfg.autopilotLoop.maxIterations,
        completionMode: cfg.autopilotLoop.completionMode,
        completionPromise: cfg.autopilotLoop.completionPromise,
      },
    }),
    createContinuationHook({
      directory,
      client: ctx.client,
    }),
    createSafetyHook({
      directory,
      orphanMaxAgeHours: 12,
    }),
  ]
  if (!cfg.hooks.enabled) {
    return []
  }
  return resolveHookOrder(hooks, cfg.hooks.order, cfg.hooks.disabled)
}

// Creates gateway plugin entrypoint with deterministic hook dispatch.
export default function GatewayCorePlugin(ctx: GatewayContext): {
  event(input: GatewayEventPayload): Promise<void>
  "tool.execute.before"(input: ToolBeforeInput, output: ToolBeforeOutput): Promise<void>
  "chat.message"(input: ChatMessageInput): Promise<void>
} {
  const hooks = configuredHooks(ctx)
  const directory = typeof ctx.directory === "string" && ctx.directory.trim() ? ctx.directory : process.cwd()

  // Dispatches plugin lifecycle event to all enabled hooks in order.
  async function event(input: GatewayEventPayload): Promise<void> {
    for (const hook of hooks) {
      await hook.event(input.event.type, {
        properties: input.event.properties,
        directory,
      })
    }
  }

  // Dispatches slash command interception event to ordered hooks.
  async function toolExecuteBefore(input: ToolBeforeInput, output: ToolBeforeOutput): Promise<void> {
    for (const hook of hooks) {
      await hook.event("tool.execute.before", { input, output, directory })
    }
  }

  // Dispatches chat message lifecycle signal to ordered hooks.
  async function chatMessage(input: ChatMessageInput): Promise<void> {
    for (const hook of hooks) {
      await hook.event("chat.message", {
        properties: {
          sessionID: input.sessionID,
        },
        directory,
      })
    }
  }

  return {
    event,
    "tool.execute.before": toolExecuteBefore,
    "chat.message": chatMessage,
  }
}
