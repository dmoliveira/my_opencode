// Creates autopilot loop hook placeholder for gateway composition.
export function createAutopilotLoopHook() {
    return {
        id: "autopilot-loop",
        priority: 100,
        async event(_type, _payload) {
            return;
        },
    };
}
