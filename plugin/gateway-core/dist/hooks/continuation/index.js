// Creates continuation helper hook placeholder for gateway composition.
export function createContinuationHook() {
    return {
        id: "continuation",
        priority: 200,
        async event(_type, _payload) {
            return;
        },
    };
}
