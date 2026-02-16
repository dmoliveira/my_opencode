// Declares stable reason-code constants used by gateway hooks.
export const REASON_CODES = {
  LOOP_STARTED: "gateway_loop_started",
  LOOP_STOPPED: "gateway_loop_stopped",
  LOOP_IDLE_CONTINUED: "gateway_loop_idle_continued",
  LOOP_MAX_ITERATIONS: "gateway_loop_max_iterations_reached",
  LOOP_COMPLETED_PROMISE: "gateway_loop_promise_detected",
  LOOP_COMPLETED_OBJECTIVE: "gateway_loop_objective_completed",
  LOOP_RUNTIME_BOOTSTRAPPED: "gateway_loop_runtime_bootstrapped",
  LOOP_COMPLETION_IGNORED_INCOMPLETE_RUNTIME:
    "gateway_loop_completion_ignored_incomplete_runtime",
  LOOP_COMPLETION_STALLED_RUNTIME: "gateway_loop_completion_stalled_runtime",
  LOOP_ORPHAN_CLEANED: "gateway_loop_orphan_cleaned",
  RUNTIME_PLUGIN_READY: "gateway_plugin_ready",
  RUNTIME_PLUGIN_DISABLED: "gateway_plugin_disabled",
  RUNTIME_PLUGIN_RUNTIME_UNAVAILABLE: "gateway_plugin_runtime_unavailable",
  RUNTIME_PLUGIN_NOT_READY: "gateway_plugin_not_ready",
  LOOP_STATE_AVAILABLE: "loop_state_available",
  LOOP_STATE_BRIDGE_IGNORED_IN_PLUGIN_MODE: "bridge_state_ignored_in_plugin_mode",
} as const

// Declares reason-code literal union for gateway outputs.
export type GatewayReasonCode = (typeof REASON_CODES)[keyof typeof REASON_CODES]
