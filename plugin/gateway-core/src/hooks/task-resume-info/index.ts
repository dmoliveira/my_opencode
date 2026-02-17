import type { GatewayHook } from "../registry.js"

interface ToolAfterPayload {
  input?: { tool?: string }
  output?: { output?: unknown }
}

const RESUME_HINT =
  "Resume hint: keep the returned task_id and reuse it to continue the same subagent session."
const CONTINUE_HINT =
  "Continuation hint: pending work remains; continue execution directly and avoid asking for extra confirmation turns."

// Creates hook that appends resume hints after task tool responses.
export function createTaskResumeInfoHook(options: { enabled: boolean }): GatewayHook {
  return {
    id: "task-resume-info",
    priority: 340,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase()
      if (tool !== "task") {
        return
      }
      const output = eventPayload.output
      if (!output || typeof output.output !== "string") {
        return
      }
      const text = output.output
      let next = text
      if (next.includes("task_id") && !next.includes(RESUME_HINT)) {
        next += `\n\n${RESUME_HINT}`
      }
      if (next.includes("<CONTINUE-LOOP>") && !next.includes(CONTINUE_HINT)) {
        next += `\n\n${CONTINUE_HINT}`
      }
      output.output = next
    },
  }
}
