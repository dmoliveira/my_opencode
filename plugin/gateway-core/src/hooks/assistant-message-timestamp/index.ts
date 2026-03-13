import type { GatewayHook } from "../registry.js";

interface SessionIdlePayload {
  output?: { output?: unknown };
}

interface ChatMessagePart {
  type?: string;
  text?: string;
}

interface ChatTransformMessage {
  info?: { role?: string };
  parts?: ChatMessagePart[];
}

interface ChatMessagesTransformPayload {
  output?: {
    messages?: ChatTransformMessage[];
  };
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

function prependTimestampToText(text: string, timestamp: string): string {
  const trimmed = text.trim();
  if (!trimmed || trimmed.startsWith(TIMESTAMP_PREFIX_LABEL)) {
    return text;
  }
  return `${timestamp}\n${trimmed}`;
}

function prependTimestampToLatestAssistantMessage(
  messages: ChatTransformMessage[] | undefined,
  timestamp: string,
): void {
  if (!Array.isArray(messages) || messages.length === 0) {
    return;
  }
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.info?.role !== "assistant") {
      continue;
    }
    const parts = Array.isArray(message.parts) ? message.parts : [];
    const firstTextPart = parts.find(
      (part) => part?.type === "text" && typeof part.text === "string",
    );
    if (firstTextPart) {
      firstTextPart.text = prependTimestampToText(firstTextPart.text ?? "", timestamp);
      return;
    }
    parts.unshift({ type: "text", text: timestamp });
    message.parts = parts;
    return;
  }
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
      if (!options.enabled) {
        return;
      }
      const timestamp = formatAssistantMessageTimestamp(now());
      if (type === "experimental.chat.messages.transform") {
        const eventPayload = (payload ?? {}) as ChatMessagesTransformPayload;
        prependTimestampToLatestAssistantMessage(eventPayload.output?.messages, timestamp);
        return;
      }
      if (type !== "session.idle") {
        return;
      }
      const eventPayload = (payload ?? {}) as SessionIdlePayload;
      if (typeof eventPayload.output?.output !== "string") {
        return;
      }
      eventPayload.output.output = prependTimestampToText(
        eventPayload.output.output,
        timestamp,
      );
    },
  };
}
