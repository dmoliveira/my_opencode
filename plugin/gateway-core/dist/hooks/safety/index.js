// Creates safety guard hook placeholder for gateway composition.
export function createSafetyHook() {
    return {
        id: "safety",
        priority: 300,
        async event(_type, _payload) {
            return;
        },
    };
}
