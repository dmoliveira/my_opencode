export declare const REASON_CODES: {
    readonly LOOP_STARTED: "gateway_loop_started";
    readonly LOOP_STOPPED: "gateway_loop_stopped";
    readonly LOOP_IDLE_CONTINUED: "gateway_loop_idle_continued";
    readonly LOOP_MAX_ITERATIONS: "gateway_loop_max_iterations_reached";
    readonly LOOP_COMPLETED_PROMISE: "gateway_loop_promise_detected";
    readonly LOOP_COMPLETED_OBJECTIVE: "gateway_loop_objective_completed";
    readonly LOOP_RUNTIME_BOOTSTRAPPED: "gateway_loop_runtime_bootstrapped";
    readonly LOOP_COMPLETION_IGNORED_INCOMPLETE_RUNTIME: "gateway_loop_completion_ignored_incomplete_runtime";
    readonly LOOP_ORPHAN_CLEANED: "gateway_loop_orphan_cleaned";
    readonly RUNTIME_PLUGIN_READY: "gateway_plugin_ready";
    readonly RUNTIME_PLUGIN_DISABLED: "gateway_plugin_disabled";
    readonly RUNTIME_PLUGIN_RUNTIME_UNAVAILABLE: "gateway_plugin_runtime_unavailable";
    readonly RUNTIME_PLUGIN_NOT_READY: "gateway_plugin_not_ready";
    readonly LOOP_STATE_AVAILABLE: "loop_state_available";
    readonly LOOP_STATE_BRIDGE_IGNORED_IN_PLUGIN_MODE: "bridge_state_ignored_in_plugin_mode";
};
export type GatewayReasonCode = (typeof REASON_CODES)[keyof typeof REASON_CODES];
