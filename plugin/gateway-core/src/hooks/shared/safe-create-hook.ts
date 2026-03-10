import { writeGatewayEventAudit } from "../../audit/event-audit.js";

function errorDetails(error: unknown): {
  error_name?: string;
  error_message?: string;
} {
  if (error instanceof Error) {
    return {
      error_name: error.name,
      error_message: error.message,
    };
  }
  if (typeof error === "string" && error.trim()) {
    return { error_message: error.trim() };
  }
  return {};
}

export function safeCreateHook<T>(input: {
  directory: string;
  hookId: string;
  factory: () => T;
}): T | null {
  try {
    return input.factory();
  } catch (error) {
    writeGatewayEventAudit(input.directory, {
      hook: input.hookId,
      stage: "init",
      reason_code: "hook_creation_failed",
      ...errorDetails(error),
    });
    return null;
  }
}
