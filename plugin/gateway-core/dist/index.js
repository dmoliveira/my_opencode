import { loadGatewayConfig } from "./config/load.js";
import { createAutopilotLoopHook } from "./hooks/autopilot-loop/index.js";
import { createContinuationHook } from "./hooks/continuation/index.js";
import { createSafetyHook } from "./hooks/safety/index.js";
import { resolveHookOrder } from "./hooks/registry.js";
// Creates ordered hook list using gateway config and default hooks.
function configuredHooks(ctx) {
    const directory = typeof ctx.directory === "string" && ctx.directory.trim() ? ctx.directory : process.cwd();
    const cfg = loadGatewayConfig(ctx.config);
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
            orphanMaxAgeHours: cfg.autopilotLoop.orphanMaxAgeHours,
        }),
    ];
    if (!cfg.hooks.enabled) {
        return [];
    }
    return resolveHookOrder(hooks, cfg.hooks.order, cfg.hooks.disabled);
}
// Creates gateway plugin entrypoint with deterministic hook dispatch.
export default function GatewayCorePlugin(ctx) {
    const hooks = configuredHooks(ctx);
    const directory = typeof ctx.directory === "string" && ctx.directory.trim() ? ctx.directory : process.cwd();
    // Dispatches plugin lifecycle event to all enabled hooks in order.
    async function event(input) {
        for (const hook of hooks) {
            await hook.event(input.event.type, {
                properties: input.event.properties,
                directory,
            });
        }
    }
    // Dispatches slash command interception event to ordered hooks.
    async function toolExecuteBefore(input, output) {
        for (const hook of hooks) {
            await hook.event("tool.execute.before", { input, output, directory });
        }
    }
    // Dispatches chat message lifecycle signal to ordered hooks.
    async function chatMessage(input) {
        for (const hook of hooks) {
            await hook.event("chat.message", {
                properties: {
                    sessionID: input.sessionID,
                },
                directory,
            });
        }
    }
    return {
        event,
        "tool.execute.before": toolExecuteBefore,
        "chat.message": chatMessage,
    };
}
