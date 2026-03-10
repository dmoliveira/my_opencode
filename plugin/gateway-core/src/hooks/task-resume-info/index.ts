import type { GatewayHook } from "../registry.js";

interface ToolAfterPayload {
  input?: { tool?: string };
  output?: { output?: unknown };
}

const RESUME_HINT =
  "Resume hint: keep the returned task_id and reuse it to continue the same subagent session.";
const CONTINUE_HINT =
  "Continuation hint: pending work remains; continue execution directly and avoid asking for extra confirmation turns.";
const VERIFICATION_HEADER =
  "Verification hint: review the subagent result before moving on.";

function extractResumeTarget(text: string): string {
  const patterns = [
    /Session ID:\s*(ses_[a-zA-Z0-9]+)/,
    /session_id["':\s]+(ses_[a-zA-Z0-9]+)/i,
    /task_id["':\s]+([a-zA-Z0-9_-]+)/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) {
      return match[1];
    }
  }
  return "";
}

function buildVerificationHint(resumeTarget: string): string {
  const retryLine = resumeTarget
    ? `If follow-up fixes are needed, continue the same worker context with \`task_id/session_id=${resumeTarget}\` instead of spawning a brand new thread.`
    : "If follow-up fixes are needed, continue the same worker context instead of spawning a brand new thread.";
  return [
    VERIFICATION_HEADER,
    "- Check the subagent's claimed changes and validation evidence before proceeding.",
    "- Reuse the returned worker context for fixes so investigation stays attached to the same thread.",
    `- ${retryLine}`,
  ].join("\n");
}

// Creates hook that appends resume hints after task tool responses.
export function createTaskResumeInfoHook(options: {
  enabled: boolean;
}): GatewayHook {
  return {
    id: "task-resume-info",
    priority: 340,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "tool.execute.after") {
        return;
      }
      const eventPayload = (payload ?? {}) as ToolAfterPayload;
      const tool = String(eventPayload.input?.tool ?? "").toLowerCase();
      if (tool !== "task") {
        return;
      }
      const output = eventPayload.output;
      if (!output || typeof output.output !== "string") {
        return;
      }
      const text = output.output;
      let next = text;
      if (next.includes("task_id") && !next.includes(RESUME_HINT)) {
        next += `\n\n${RESUME_HINT}`;
      }
      if (next.includes("<CONTINUE-LOOP>") && !next.includes(CONTINUE_HINT)) {
        next += `\n\n${CONTINUE_HINT}`;
      }
      const resumeTarget = extractResumeTarget(next);
      if (resumeTarget && !next.includes(VERIFICATION_HEADER)) {
        next += `\n\n${buildVerificationHint(resumeTarget)}`;
      }
      output.output = next;
    },
  };
}
