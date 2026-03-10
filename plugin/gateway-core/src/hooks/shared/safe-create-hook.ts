import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import {
  describeHookFailure,
  isCriticalGatewayHookId,
  normalizeHookError,
  surfaceGatewayHookFailure,
} from "./hook-failure.js";

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
  critical?: boolean;
}): T | null {
  try {
    return input.factory();
  } catch (error) {
    const critical = input.critical ?? isCriticalGatewayHookId(input.hookId);
    const failure = describeHookFailure(error);
    writeGatewayEventAudit(input.directory, {
      hook: input.hookId,
      stage: "init",
      reason_code: critical
        ? "critical_hook_creation_failed"
        : "hook_creation_failed",
      critical,
      ...errorDetails(error),
    });
    surfaceGatewayHookFailure(
      `${critical ? "critical " : ""}hook ${input.hookId} failed during init: ${failure}`,
    );
    if (critical) {
      throw normalizeHookError(
        error,
        `critical hook ${input.hookId} failed during init: ${failure}`,
      );
    }
    return null;
  }
}
