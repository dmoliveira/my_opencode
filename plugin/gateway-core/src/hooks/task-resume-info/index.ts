import type { GatewayHook } from "../registry.js"

interface ToolAfterPayload {
  input?: { tool?: string }
  output?: { output?: unknown }
}

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
      if (typeof eventPayload.output?.output !== "string") {
        return
      }
      if (eventPayload.output.output.includes("task_id")) {
        eventPayload.output.output += "\n\nResume hint: keep the returned task_id and reuse it to continue the same subagent session."
      }
    },
  }
}
