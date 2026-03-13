import type { GatewayHook } from "../registry.js";

interface SessionIdlePayload {
  output?: { output?: unknown };
}

const TIMESTAMP_PREFIX_LABEL = "[";

export function formatAssistantMessageTimestamp(timestamp: number): string {
  const value = new Date(timestamp);
  const year = value.getFullYear();
  const month = value.getMonth() + 1;
  const day = value.getDate();
  const hours = String(value.getHours()).padStart(2, "0");
  const minutes = String(value.getMinutes()).padStart(2, "0");
  const seconds = String(value.getSeconds()).padStart(2, "0");
  return `[${year}-${month}-${day} ${hours}:${minutes}:${seconds}]`;
}

export function createAssistantMessageTimestampHook(options: {
  enabled: boolean;
  now?: () => number;
}): GatewayHook {
  const now = options.now ?? ((): number => Date.now());
  return {
    id: "assistant-message-timestamp",
    priority: 341,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled || type !== "session.idle") {
        return;
      }
      const eventPayload = (payload ?? {}) as SessionIdlePayload;
      if (typeof eventPayload.output?.output !== "string") {
        return;
      }
      const output = eventPayload.output.output.trim();
      if (!output || output.startsWith(TIMESTAMP_PREFIX_LABEL)) {
        return;
      }
      eventPayload.output.output = `${formatAssistantMessageTimestamp(now())}\n${output}`;
    },
  };
}
