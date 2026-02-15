import { loadGatewayConfig } from "./config/load.js";
import { writeGatewayEventAudit } from "./audit/event-audit.js";
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
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "event_dispatch",
            event_type: input.event.type,
            hook_count: hooks.length,
        });
        for (const hook of hooks) {
            await hook.event(input.event.type, {
                properties: input.event.properties,
                directory,
            });
        }
    }
    // Dispatches slash command interception event to ordered hooks.
    async function toolExecuteBefore(input, output) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "tool_execute_before_dispatch",
            event_type: "tool.execute.before",
            tool: input.tool,
            hook_count: hooks.length,
            has_command: typeof output.args?.command === "string" && output.args.command.trim().length > 0,
        });
        for (const hook of hooks) {
            await hook.event("tool.execute.before", { input, output, directory });
        }
    }
    // Dispatches chat message lifecycle signal to ordered hooks.
    async function chatMessage(input) {
        writeGatewayEventAudit(directory, {
            hook: "gateway-core",
            stage: "dispatch",
            reason_code: "chat_message_dispatch",
            event_type: "chat.message",
            has_session_id: typeof input.sessionID === "string" && input.sessionID.trim().length > 0,
            hook_count: hooks.length,
        });
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
