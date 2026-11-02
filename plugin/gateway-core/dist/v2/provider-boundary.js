/**
 * Registers the model-context portion of the V2 redaction port. This is not a
 * complete provider boundary: later plugins and raw HTTP/WebSocket hooks can
 * still modify requests. Do not enable this as a standalone security plugin.
 */
export async function registerV2ContextRedaction(session, redactor) {
    const registrations = [];
    try {
        for (const kind of ["context", "compaction", "generate", "title"]) {
            registrations.push(await session.hook(kind, async (event) => {
                if (!Array.isArray(event.system) || !Array.isArray(event.messages)) {
                    throw new Error("invalid V2 model context; refusing unscanned request");
                }
                await redactor.redactMutableValueAsync(event.system);
                await redactor.redactMutableValueAsync(event.messages);
            }));
        }
    }
    catch (error) {
        await Promise.allSettled(registrations.map((registration) => registration.dispose()));
        throw error;
    }
    return async () => {
        await Promise.all(registrations.map((registration) => registration.dispose()));
    };
}
