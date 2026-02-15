import { loadGatewayConfig } from "./config/load.js";
import { createAutopilotLoopHook } from "./hooks/autopilot-loop/index.js";
import { createContinuationHook } from "./hooks/continuation/index.js";
import { createSafetyHook } from "./hooks/safety/index.js";
import { resolveHookOrder } from "./hooks/registry.js";
// Creates ordered hook list using gateway config and default hooks.
function configuredHooks(rawConfig) {
    const cfg = loadGatewayConfig(rawConfig);
    const hooks = [createAutopilotLoopHook(), createContinuationHook(), createSafetyHook()];
    if (!cfg.hooks.enabled) {
        return [];
    }
    return resolveHookOrder(hooks, cfg.hooks.order, cfg.hooks.disabled);
}
// Creates gateway plugin entrypoint with deterministic hook dispatch.
export default function GatewayCorePlugin(ctx) {
    const hooks = configuredHooks(ctx.config);
    // Dispatches plugin lifecycle event to all enabled hooks in order.
    async function event(input) {
        for (const hook of hooks) {
            await hook.event(input.event.type, input.event.properties);
        }
    }
    return { event };
}
