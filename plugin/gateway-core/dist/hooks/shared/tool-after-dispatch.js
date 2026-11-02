import { dispatchGatewayHookEvent } from "./hook-dispatch.js";
// Internal dispatch boundary: receipts observe native output before presentation.
export async function dispatchToolAfterHooks(selectedHooks, payload, dispatch = dispatchGatewayHookEvent) {
    // Keep cancellation bound to native identity even if a later hook mutates input.
    const cancellationInput = { ...payload.input };
    const receiver = selectedHooks.find((hook) => hook.id === "dependency-risk-guard");
    const ledger = selectedHooks.find((hook) => hook.id === "validation-evidence-ledger");
    const ordered = [
        receiver,
        ledger,
        ...selectedHooks.filter((hook) => hook.id !== "dependency-risk-guard" &&
            hook.id !== "validation-evidence-ledger"),
    ].filter((hook) => hook !== undefined);
    for (const hook of ordered) {
        const result = await dispatch({
            hook,
            eventType: "tool.execute.after",
            payload,
            directory: payload.directory,
        });
        if (!result.ok) {
            // Cancellation is targeted and awaited even for failures the pipeline tolerates.
            // The normal dispatcher isolates cleanup errors so the original error wins.
            if (receiver) {
                await dispatch({
                    hook: receiver,
                    eventType: "tool.execute.after.error",
                    payload: { input: cancellationInput, directory: payload.directory },
                    directory: payload.directory,
                });
            }
            if (result.critical || result.blocked)
                throw result.error;
        }
    }
}
