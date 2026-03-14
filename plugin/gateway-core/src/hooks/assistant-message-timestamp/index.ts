import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import type { GatewayHook } from "../registry.js";
import {
  consumeLlmDecisionFallbackNotice,
  peekLlmDecisionFallbackNotice,
} from "../shared/llm-decision-runtime.js";

interface SessionIdlePayload {
  output?: { output?: unknown };
  directory?: string;
  properties?: {
    sessionID?: string;
    sessionId?: string;
    info?: { id?: string };
  };
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
  directory?: string;
}

interface TextCompletePayload {
  output?: {
    text?: string;
  };
  directory?: string;
}

interface AssistantEventProperties {
  role?: string;
  sessionID?: string;
  sessionId?: string;
  text?: string;
  content?: string;
  delta?: string;
  field?: string;
  messageID?: string;
  messageId?: string;
  partID?: string;
  partId?: string;
  info?: { role?: string; id?: string; sessionID?: string; sessionId?: string };
  part?: (ChatMessagePart & { messageID?: string; messageId?: string; id?: string });
  parts?: ChatMessagePart[];
  messageParts?: ChatMessagePart[];
  message?: { parts?: ChatMessagePart[]; text?: string } | string;
}

interface AssistantLifecyclePayload {
  properties?: AssistantEventProperties;
  directory?: string;
}

const TIMESTAMP_PREFIX_LABEL = "[";
const TARGET_EVENT_TYPES = new Set([
  "message.updated",
  "message.part.updated",
  "message.part.delta",
]);

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

function debugAuditEnabled(): boolean {
  return process.env.MY_OPENCODE_ASSISTANT_TIMESTAMP_DEBUG === "1";
}

function prependTimestampToText(text: string, timestamp: string): string {
  const trimmed = text.trim();
  if (!trimmed || trimmed.startsWith(TIMESTAMP_PREFIX_LABEL)) {
    return text;
  }
  return `${timestamp}\n${trimmed}`;
}

function prependNoticeToText(text: string, notice: string): string {
  const trimmed = text.trim();
  const normalizedNotice = notice.trim();
  if (!trimmed || !normalizedNotice || trimmed.includes(normalizedNotice)) {
    return text;
  }
  if (trimmed.startsWith(TIMESTAMP_PREFIX_LABEL)) {
    const newlineIndex = trimmed.indexOf("\n");
    if (newlineIndex >= 0) {
      const header = trimmed.slice(0, newlineIndex);
      const remainder = trimmed.slice(newlineIndex + 1).trimStart();
      return `${header}\n${normalizedNotice}\n${remainder}`;
    }
    return `${trimmed}\n${normalizedNotice}`;
  }
  return `${normalizedNotice}\n${trimmed}`;
}

function decorateAssistantText(
  text: string,
  timestamp: string,
  notice: string,
): { text: string; changed: boolean; noticeApplied: boolean } {
  const timestamped = prependTimestampToText(text, timestamp);
  const next = notice ? prependNoticeToText(timestamped, notice) : timestamped;
  return {
    text: next,
    changed: next !== text,
    noticeApplied: Boolean(notice && next.includes(notice) && !String(text).includes(notice)),
  };
}

function prependTimestampToParts(
  parts: ChatMessagePart[] | undefined,
  timestamp: string,
  notice: string,
): { changed: boolean; noticeApplied: boolean } {
  if (!Array.isArray(parts) || parts.length === 0) {
    return { changed: false, noticeApplied: false };
  }
  const textPart = parts.find(
    (part) => part?.type === "text" && typeof part.text === "string",
  );
  if (!textPart) {
    return { changed: false, noticeApplied: false };
  }
  const result = decorateAssistantText(textPart.text ?? "", timestamp, notice);
  if (!result.changed) {
    return { changed: false, noticeApplied: false };
  }
  textPart.text = result.text;
  return { changed: true, noticeApplied: result.noticeApplied };
}

function prependTimestampToLatestAssistantMessage(
  messages: ChatTransformMessage[] | undefined,
  timestamp: string,
  notice: string,
): boolean {
  if (!Array.isArray(messages) || messages.length === 0) {
    return false;
  }
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.info?.role !== "assistant") {
      continue;
    }
    const parts = Array.isArray(message.parts) ? message.parts : [];
    if (prependTimestampToParts(parts, timestamp, notice).changed) {
      return true;
    }
    parts.unshift({ type: "text", text: notice ? `${timestamp}\n${notice}` : timestamp });
    message.parts = parts;
    return true;
  }
  return false;
}

function assistantRole(properties: AssistantEventProperties | undefined): string {
  return String(properties?.info?.role ?? properties?.role ?? "").trim();
}

function resolveMessageId(properties: AssistantEventProperties | undefined): string {
  return String(
    properties?.info?.id ??
      properties?.messageID ??
      properties?.messageId ??
      properties?.part?.messageID ??
      properties?.part?.messageId ??
      "",
  ).trim();
}

function resolvePartId(properties: AssistantEventProperties | undefined): string {
  return String(properties?.partID ?? properties?.partId ?? properties?.part?.id ?? "").trim();
}

function resolveSessionId(properties: AssistantEventProperties | undefined): string {
  return String(
    properties?.info?.sessionID ??
      properties?.info?.sessionId ??
      properties?.sessionID ??
      properties?.sessionId ??
      "",
  ).trim();
}

function prependTimestampToAssistantLifecyclePayload(
  properties: AssistantEventProperties | undefined,
  timestamp: string,
  notice: string,
): { changed: boolean; noticeApplied: boolean } {
  if (!properties || assistantRole(properties) !== "assistant") {
    return { changed: false, noticeApplied: false };
  }
  const topLevelParts = prependTimestampToParts(properties.parts, timestamp, notice);
  if (topLevelParts.changed) {
    return topLevelParts;
  }
  const messageParts = prependTimestampToParts(properties.messageParts, timestamp, notice);
  if (messageParts.changed) {
    return messageParts;
  }
  if (
    properties.message &&
    typeof properties.message === "object" &&
    Array.isArray(properties.message.parts)
  ) {
    const nestedParts = prependTimestampToParts(properties.message.parts, timestamp, notice);
    if (nestedParts.changed) {
      return nestedParts;
    }
  }
  if (properties.part?.type === "text" && typeof properties.part.text === "string") {
    const result = decorateAssistantText(properties.part.text, timestamp, notice);
    if (result.changed) {
      properties.part.text = result.text;
      return { changed: true, noticeApplied: result.noticeApplied };
    }
  }
  if (properties.message && typeof properties.message === "object") {
    const messageText = properties.message.text;
    if (typeof messageText === "string") {
      const result = decorateAssistantText(messageText, timestamp, notice);
      if (result.changed) {
        properties.message.text = result.text;
        return { changed: true, noticeApplied: result.noticeApplied };
      }
    }
  }
  for (const key of ["text", "content", "delta"] as const) {
    const value = properties[key];
    if (typeof value !== "string") {
      continue;
    }
    const result = decorateAssistantText(value, timestamp, notice);
    if (result.changed) {
      properties[key] = result.text;
      return { changed: true, noticeApplied: result.noticeApplied };
    }
  }
  return { changed: false, noticeApplied: false };
}

function writeDebugAudit(
  directory: string | undefined,
  type: string,
  properties: AssistantEventProperties | undefined,
  applied: boolean,
): void {
  if (!debugAuditEnabled() || !directory || !TARGET_EVENT_TYPES.has(type)) {
    return;
  }
  const messageValue = properties?.message;
  writeGatewayEventAudit(directory, {
    hook: "assistant-message-timestamp",
    stage: applied ? "inject" : "state",
    reason_code: applied
      ? "assistant_timestamp_lifecycle_applied"
      : "assistant_timestamp_lifecycle_noop",
    event_type: type,
    role: assistantRole(properties),
    message_id: resolveMessageId(properties),
    part_id: resolvePartId(properties),
    field: String(properties?.field ?? ""),
    top_level_keys: properties ? Object.keys(properties).join(",") : "",
    info_keys:
      properties?.info && typeof properties.info === "object"
        ? Object.keys(properties.info).join(",")
        : "",
    part_keys:
      properties?.part && typeof properties.part === "object"
        ? Object.keys(properties.part).join(",")
        : "",
    has_part: Boolean(properties?.part),
    has_parts: Array.isArray(properties?.parts),
    has_message_parts:
      Boolean(messageValue) &&
      typeof messageValue === "object" &&
      Array.isArray(messageValue.parts),
    text_preview:
      typeof properties?.text === "string"
        ? properties.text.slice(0, 80)
        : typeof properties?.delta === "string"
          ? properties.delta.slice(0, 80)
        : typeof properties?.part?.text === "string"
          ? properties.part.text.slice(0, 80)
          : Array.isArray(properties?.parts) && typeof properties.parts[0]?.text === "string"
            ? properties.parts[0].text.slice(0, 80)
            : "",
  });
}

export function createAssistantMessageTimestampHook(options: {
  enabled: boolean;
  now?: () => number;
}): GatewayHook {
  const now = options.now ?? ((): number => Date.now());
  const assistantMessageIds = new Set<string>();
  const stampedPartIds = new Set<string>();
  const stampedMessageIds = new Set<string>();
  return {
    id: "assistant-message-timestamp",
    priority: 341,
    async event(type: string, payload: unknown): Promise<void> {
      if (!options.enabled) {
        return;
      }
      if (type === "session.deleted") {
        assistantMessageIds.clear();
        stampedPartIds.clear();
        stampedMessageIds.clear();
        return;
      }
      const timestamp = formatAssistantMessageTimestamp(now());
      if (type === "experimental.chat.messages.transform") {
        const eventPayload = (payload ?? {}) as ChatMessagesTransformPayload;
        prependTimestampToLatestAssistantMessage(eventPayload.output?.messages, timestamp, "");
        return;
      }
      if (type === "experimental.text.complete") {
        const eventPayload = (payload ?? {}) as TextCompletePayload;
        if (typeof eventPayload.output?.text === "string") {
          eventPayload.output.text = prependTimestampToText(eventPayload.output.text, timestamp);
        }
        return;
      }
      if (TARGET_EVENT_TYPES.has(type)) {
        const eventPayload = (payload ?? {}) as AssistantLifecyclePayload;
        const properties = eventPayload.properties;
        let applied = false;
        const directory = typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : "";
        const sessionId = resolveSessionId(properties);
        const notice =
          directory && sessionId ? peekLlmDecisionFallbackNotice(directory, sessionId) : "";
        if (type === "message.updated") {
          const messageId = resolveMessageId(properties);
          if (assistantRole(properties) === "assistant" && messageId) {
            assistantMessageIds.add(messageId);
          }
          const result = prependTimestampToAssistantLifecyclePayload(properties, timestamp, notice);
          applied = result.changed;
          if (result.noticeApplied) {
            consumeLlmDecisionFallbackNotice(directory, sessionId);
          }
        } else if (type === "message.part.updated") {
          const messageId = resolveMessageId(properties);
          const partId = resolvePartId(properties);
          if (
            messageId &&
            assistantMessageIds.has(messageId) &&
            properties?.part?.type === "text" &&
            typeof properties.part.text === "string" &&
            !stampedPartIds.has(partId || messageId)
          ) {
            const result = decorateAssistantText(properties.part.text, timestamp, notice);
            if (result.changed) {
              properties.part.text = result.text;
              stampedPartIds.add(partId || messageId);
              stampedMessageIds.add(messageId);
              applied = true;
              if (result.noticeApplied) {
                consumeLlmDecisionFallbackNotice(directory, sessionId);
              }
            }
          }
        } else if (type === "message.part.delta") {
          const messageId = resolveMessageId(properties);
          const partId = resolvePartId(properties);
          const stampKey = partId || messageId;
          const deltaText = properties?.delta;
          if (
            messageId &&
            assistantMessageIds.has(messageId) &&
            typeof deltaText === "string" &&
            !stampedPartIds.has(stampKey)
          ) {
            const result = decorateAssistantText(deltaText, timestamp, notice);
            if (result.changed && properties) {
              properties.delta = result.text;
              stampedPartIds.add(stampKey);
              stampedMessageIds.add(messageId);
              applied = true;
              if (result.noticeApplied) {
                consumeLlmDecisionFallbackNotice(directory, sessionId);
              }
            }
          }
        }
        writeDebugAudit(eventPayload.directory, type, eventPayload.properties, applied);
        return;
      }
      if (type !== "session.idle") {
        return;
      }
      const eventPayload = (payload ?? {}) as SessionIdlePayload;
      if (typeof eventPayload.output?.output !== "string") {
        return;
      }
      const directory =
        typeof eventPayload.directory === "string" && eventPayload.directory.trim()
          ? eventPayload.directory
          : "";
      const sessionId = String(
        eventPayload.properties?.sessionID ??
          eventPayload.properties?.sessionId ??
          eventPayload.properties?.info?.id ??
          "",
      ).trim();
      const notice =
        directory && sessionId ? peekLlmDecisionFallbackNotice(directory, sessionId) : "";
      const result = decorateAssistantText(eventPayload.output.output, timestamp, notice);
      eventPayload.output.output = result.text;
      if (result.noticeApplied) {
        consumeLlmDecisionFallbackNotice(directory, sessionId);
      }
    },
  };
}
