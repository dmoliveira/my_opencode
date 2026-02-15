// Declares stable reason-code constants used by gateway hooks.
export const REASON_CODES = {
  LOOP_STARTED: "gateway_loop_started",
  LOOP_STOPPED: "gateway_loop_stopped",
  LOOP_IDLE_CONTINUED: "gateway_loop_idle_continued",
  LOOP_MAX_ITERATIONS: "gateway_loop_max_iterations_reached",
  LOOP_COMPLETED_PROMISE: "gateway_loop_promise_detected",
  LOOP_COMPLETED_OBJECTIVE: "gateway_loop_objective_completed",
  LOOP_ORPHAN_CLEANED: "gateway_loop_orphan_cleaned",
} as const

// Declares reason-code literal union for gateway outputs.
export type GatewayReasonCode = (typeof REASON_CODES)[keyof typeof REASON_CODES]
