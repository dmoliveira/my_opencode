import type { SecretRedactor } from "../hooks/shared/secret-redaction.js"
import type { ToolHooks } from "./types.js"

/** Redact successful V2 tool results before they are returned to the session. */
export async function registerV2ToolOutputRedaction(
  tool: ToolHooks,
  redactor: Pick<SecretRedactor, "redactMutableValueAsync">,
): Promise<() => Promise<void>> {
  const registration = await tool.hook("execute.after", async (event) => {
    // Error objects have a distinct host-owned representation. Their model-visible
    // content must still be scanned by the model and transport boundaries.
    if (event.status !== "completed") return
    const wrapper = { result: event.result }
    await redactor.redactMutableValueAsync(wrapper)
    event.result = wrapper.result
  })
  return () => registration.dispose()
}
