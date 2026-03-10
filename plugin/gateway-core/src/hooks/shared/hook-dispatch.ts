import { writeGatewayEventAudit } from "../../audit/event-audit.js";
import type { GatewayHook } from "../registry.js";
import {
  describeHookFailure,
  isCriticalGatewayHookId,
  isIntentionalHookBlock,
  normalizeHookError,
  surfaceGatewayHookFailure,
} from "./hook-failure.js";

export interface HookDispatchResult {
  ok: boolean;
  critical: boolean;
  blocked: boolean;
  error?: Error;
}

export async function dispatchGatewayHookEvent(input: {
  hook: GatewayHook;
  eventType: string;
  payload: unknown;
  directory: string;
}): Promise<HookDispatchResult> {
  try {
    await input.hook.event(input.eventType, input.payload);
    return {
      ok: true,
      critical: isCriticalGatewayHookId(input.hook.id),
      blocked: false,
    };
  } catch (error) {
    const critical = isCriticalGatewayHookId(input.hook.id);
    const blocked = isIntentionalHookBlock(error);
    const failure = describeHookFailure(error);
    writeGatewayEventAudit(input.directory, {
      hook: input.hook.id,
      stage: "dispatch",
      reason_code: blocked
        ? "hook_execution_blocked"
        : critical
          ? "critical_hook_execution_failed"
          : "hook_execution_failed",
      event_type: input.eventType,
      critical,
      blocked,
      error_message: failure,
    });
    if (!blocked) {
      surfaceGatewayHookFailure(
        `${critical ? "critical " : ""}hook ${input.hook.id} failed during ${input.eventType}: ${failure}`,
      );
    }
    return {
      ok: false,
      critical,
      blocked,
      error: normalizeHookError(
        error,
        `hook ${input.hook.id} failed during ${input.eventType}: ${failure}`,
      ),
    };
  }
}
