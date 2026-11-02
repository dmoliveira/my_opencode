import { isAbsolute } from "node:path";
import { createDangerousCommandGuardHook } from "../hooks/dangerous-command-guard/index.js";
import { createNoninteractiveShellGuardHook } from "../hooks/noninteractive-shell-guard/index.js";
/**
 * Port only the two shell-command guards. This is intentionally not a V2
 * gateway entrypoint: edit, delegation and other safety hooks need their own
 * adapters and tests before the gateway can be declared active.
 */
export async function registerV2ShellGuards(tool, resolveDirectory, options) {
    const hooks = [
        createNoninteractiveShellGuardHook({ directory: options.directory, ...options.noninteractive }),
        createDangerousCommandGuardHook({ directory: options.directory, ...options.dangerous }),
    ];
    const registration = await tool.hook("execute.before", async (event) => {
        if (event.tool !== "shell")
            return;
        if (!event.input || typeof event.input !== "object" || Array.isArray(event.input)) {
            throw new Error("invalid V2 shell input; refusing unguarded execution");
        }
        const args = event.input;
        if (typeof args.command !== "string" || !args.command.trim()) {
            throw new Error("invalid V2 shell command; refusing unguarded execution");
        }
        const directory = await resolveDirectory(event.sessionID);
        if (!directory || !isAbsolute(directory)) {
            throw new Error("V2 session directory unavailable; refusing unguarded execution");
        }
        const output = { args };
        const input = {
            tool: "bash",
            sessionID: event.sessionID,
            callID: event.id,
            agent: event.agent,
        };
        for (const hook of hooks) {
            await hook.event("tool.execute.before", { input, output, directory });
        }
        event.input = output.args;
    });
    return () => registration.dispose();
}
