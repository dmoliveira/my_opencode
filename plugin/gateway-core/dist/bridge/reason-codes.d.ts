export declare const REASON_CODES: {
    readonly LOOP_STARTED: "gateway_loop_started";
    readonly LOOP_STOPPED: "gateway_loop_stopped";
    readonly LOOP_IDLE_CONTINUED: "gateway_loop_idle_continued";
    readonly LOOP_MAX_ITERATIONS: "gateway_loop_max_iterations_reached";
    readonly LOOP_COMPLETED_PROMISE: "gateway_loop_promise_detected";
    readonly LOOP_COMPLETED_OBJECTIVE: "gateway_loop_objective_completed";
};
export type GatewayReasonCode = (typeof REASON_CODES)[keyof typeof REASON_CODES];
