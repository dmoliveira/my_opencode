import type { GatewayHook } from "../registry.js"
import type { HookDispatchResult } from "./hook-dispatch.js"

export const DELEGATION_HOOK_EVENTS = [
  "session.created",
  "session.updated",
  "session.idle",
  "message.updated",
  "session.deleted",
  "tool.execute.before",
  "tool.execute.before.error",
  "tool.execute.after",
] as const

const NO_FATAL_ERROR = Symbol("no-fatal-delegation-terminal-error")

export async function dispatchDelegationTerminalHooks(input: {
  hooks: GatewayHook[]
  dispatch: (hook: GatewayHook) => Promise<HookDispatchResult>
  cleanup: () => void
}): Promise<void> {
  let firstFatal: unknown | typeof NO_FATAL_ERROR = NO_FATAL_ERROR
  try {
    for (const hook of input.hooks) {
      try {
        const result = await input.dispatch(hook)
        if (
          !result.ok &&
          (result.critical || result.blocked) &&
          firstFatal === NO_FATAL_ERROR
        ) {
          firstFatal = result.error ?? new Error(
            `fatal delegation terminal hook failure: ${hook.id}`,
          )
        }
      } catch (error) {
        if (firstFatal === NO_FATAL_ERROR) {
          firstFatal = error
        }
      }
    }
  } finally {
    try {
      input.cleanup()
    } catch (error) {
      if (firstFatal === NO_FATAL_ERROR) {
        firstFatal = error
      }
    }
  }
  if (firstFatal !== NO_FATAL_ERROR) {
    throw firstFatal
  }
}
