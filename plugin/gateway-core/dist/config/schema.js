// Defines safe gateway defaults for production usage.
export const DEFAULT_GATEWAY_CONFIG = {
    hooks: {
        enabled: true,
        disabled: [],
        order: ["autopilot-loop", "continuation", "safety"],
    },
    autopilotLoop: {
        enabled: true,
        maxIterations: 100,
        completionMode: "promise",
        completionPromise: "DONE",
    },
    quality: {
        profile: "fast",
        ts: {
            lint: true,
            typecheck: true,
            tests: false,
        },
        py: {
            selftest: true,
        },
    },
};
