const REDACTION_FAILURE = "Tool output withheld because redaction failed";
const ERROR_WITHHELD = "Tool execution failed; details withheld by gateway";
const UNSAFE_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
const PERMISSION_DECLINED = "Permission.DeclinedError";
const VERIFIED_OPENCODE_VERSIONS = ["2.2.5", "2.2.6"];
// The prototype comes from a genuine host-created decline at registration,
// independently of the event being sanitized. The event's prototype is never used.
function copyPermissionDecline(error, trustedPrototype) {
    let isDecline = false;
    try {
        if (!error || typeof error !== "object")
            return undefined;
        const descriptor = Object.getOwnPropertyDescriptor(error, "error");
        const cause = descriptor && "value" in descriptor ? descriptor.value : undefined;
        if (!cause || typeof cause !== "object")
            return undefined;
        const tag = Object.getOwnPropertyDescriptor(cause, "_tag");
        isDecline = !!tag && "value" in tag && tag.value === PERMISSION_DECLINED;
    }
    catch {
        return undefined;
    }
    if (!isDecline)
        return undefined;
    const copy = Object.create(trustedPrototype);
    Object.defineProperties(copy, {
        _tag: { value: PERMISSION_DECLINED, enumerable: true },
        name: { value: PERMISSION_DECLINED },
        message: { value: "" },
        stack: { value: "" },
        toString: { value: () => PERMISSION_DECLINED },
        toJSON: { value: () => ({ _tag: PERMISSION_DECLINED }) },
        [Symbol.for("nodejs.util.inspect.custom")]: { value: () => PERMISSION_DECLINED },
    });
    return copy;
}
async function safeErrorMessage(error, redactor) {
    try {
        if (!error || (typeof error !== "object" && typeof error !== "function"))
            return ERROR_WITHHELD;
        const descriptor = Object.getOwnPropertyDescriptor(error, "message");
        if (!descriptor || !("value" in descriptor) || typeof descriptor.value !== "string")
            return ERROR_WITHHELD;
        const candidate = { message: descriptor.value };
        await redactor.redactMutableValueAsync(candidate);
        if (typeof candidate.message !== "string" || !candidate.message.trim() || UNSAFE_CONTROL.test(candidate.message)) {
            return ERROR_WITHHELD;
        }
        return candidate.message;
    }
    catch {
        return ERROR_WITHHELD;
    }
}
/**
 * Experimental: both factories must come from trusted host capabilities.
 * The decline factory is sampled before registration and must not derive its
 * result from a tool error. A matching tag cannot authenticate a host type.
 */
export async function registerV2ToolOutputRedaction(tool, redactor, createToolError, runtimeVersion, createTrustedDecline) {
    if (typeof createToolError !== "function")
        throw new Error("V2 Tool.Error factory required");
    if (!VERIFIED_OPENCODE_VERSIONS.includes(runtimeVersion))
        throw new Error("V2 tool-output adapter requires verified OpenCode 2.2.5 or 2.2.6");
    if (typeof createTrustedDecline !== "function")
        throw new Error("V2 trusted permission-decline factory required");
    let trustedPrototype;
    try {
        const trusted = createTrustedDecline();
        if (!trusted || typeof trusted !== "object")
            throw new Error();
        const tag = Object.getOwnPropertyDescriptor(trusted, "_tag");
        const prototype = Object.getPrototypeOf(trusted);
        if (!tag || !("value" in tag) || tag.value !== PERMISSION_DECLINED || !prototype)
            throw new Error();
        trustedPrototype = prototype;
    }
    catch {
        throw new Error("V2 trusted permission-decline factory unavailable");
    }
    const registration = await tool.hook("execute.after", async (event) => {
        let status;
        try {
            status = event.status;
        }
        catch {
            throw new Error(REDACTION_FAILURE);
        }
        if (status === "error") {
            // Keep the host's control-flow type for a plain rejection without retaining
            // the original error's potentially sensitive message, cause, or metadata.
            let message = ERROR_WITHHELD;
            let cause;
            try {
                const failed = event;
                const original = failed.error;
                message = await safeErrorMessage(original, redactor);
                cause = copyPermissionDecline(original, trustedPrototype);
                failed.error = createToolError(message, cause);
            }
            catch {
                // Do not surface an exception raised by a host getter or error factory.
                throw new Error(REDACTION_FAILURE);
            }
            return;
        }
        if (status !== "completed")
            throw new Error(REDACTION_FAILURE);
        try {
            const completed = event;
            const wrapper = { result: completed.result };
            await redactor.redactMutableValueAsync(wrapper);
            completed.result = wrapper.result;
        }
        catch {
            // Never surface an untrusted redactor/assignment error or a partially scanned result.
            throw new Error(REDACTION_FAILURE);
        }
    });
    return () => registration.dispose();
}
const INTERRUPT_FAILURE = "Tool step withheld because session interruption is unresolved";
const INTERRUPT_TIMEOUT_MS = 2000;
const MAX_INTERRUPTS = 8;
const MAX_QUARANTINED = 64;
const BAD_SESSION_ID = /[\u0000-\u001f\u007f]/;
function validSessionID(id) {
    return typeof id === "string" && id.length > 0 && id.length <= 160 && id === id.trim() && !BAD_SESSION_ID.test(id);
}
// Only inspect own data properties. An opaque cause cannot be classified safely.
function cancellationKind(error) {
    try {
        if (!error || typeof error !== "object")
            return "unknown";
        const descriptor = Object.getOwnPropertyDescriptor(error, "error");
        if (!descriptor)
            return "other";
        if (!("value" in descriptor))
            return "unknown";
        const cause = descriptor.value;
        if (cause === undefined || cause === null)
            return "other";
        if (typeof cause !== "object")
            return "unknown";
        const tag = Object.getOwnPropertyDescriptor(cause, "_tag");
        if (!tag)
            return "other";
        if (!("value" in tag) || typeof tag.value !== "string")
            return "unknown";
        return tag.value === PERMISSION_DECLINED || tag.value === "QuestionTool.CancelledError" ? "stop" : "other";
    }
    catch {
        return "unknown";
    }
}
/**
 * Experimental alternative to copying a host decline prototype. It is not a
 * complete provider boundary and must not be configured as a standalone guard.
 */
export async function registerV2InterruptingToolOutputRedaction(session, tool, redactor, createToolError, runtimeVersion) {
    if (!VERIFIED_OPENCODE_VERSIONS.includes(runtimeVersion))
        throw new Error("V2 tool-output adapter requires verified OpenCode 2.2.5 or 2.2.6");
    if (typeof createToolError !== "function")
        throw new Error("V2 Tool.Error factory required");
    const registrations = [];
    const quarantined = new Map();
    let globallyClosed = false;
    let activeInterrupts = 0;
    const maybeRelease = (id, entry) => {
        if (!entry.failed && entry.idle && !entry.waiter && entry.inflight === 0 && quarantined.get(id) === entry) {
            quarantined.delete(id);
        }
    };
    const observeSettlement = (id, entry) => {
        entry.idle = false;
        if (entry.waiter || entry.failed)
            return;
        entry.waiter = true;
        void Promise.resolve().then(() => session.wait({ sessionID: id })).then(() => {
            entry.idle = true;
        }, () => {
            entry.failed = true;
        }).finally(() => {
            entry.waiter = false;
            maybeRelease(id, entry);
        });
    };
    const interrupt = async (event) => {
        let id;
        try {
            id = event.sessionID;
        }
        catch {
            globallyClosed = true;
            throw new Error(INTERRUPT_FAILURE);
        }
        if (!validSessionID(id)) {
            globallyClosed = true;
            throw new Error(INTERRUPT_FAILURE);
        }
        let entry = quarantined.get(id);
        if (!entry) {
            if (quarantined.size >= MAX_QUARANTINED) {
                globallyClosed = true;
                throw new Error(INTERRUPT_FAILURE);
            }
            entry = { inflight: 0, idle: false, waiter: false, failed: false };
            quarantined.set(id, entry);
        }
        entry.inflight += 1;
        let assignmentFailed = false;
        try {
            try {
                event.error = createToolError("Tool step stopped");
            }
            catch {
                assignmentFailed = true;
                entry.failed = true;
            }
            if (activeInterrupts >= MAX_INTERRUPTS) {
                globallyClosed = true;
                throw new Error(INTERRUPT_FAILURE);
            }
            activeInterrupts += 1;
            const pending = Promise.resolve().then(() => session.interrupt({ sessionID: id, resume: false }));
            void pending.finally(() => { activeInterrupts -= 1; }).catch(() => { });
            let timer;
            try {
                const timeout = new Promise((_, reject) => {
                    timer = setTimeout(() => reject(new Error(INTERRUPT_FAILURE)), INTERRUPT_TIMEOUT_MS);
                });
                const outcome = await Promise.race([pending, timeout]);
                if (!outcome || outcome.interrupted !== true || assignmentFailed)
                    throw new Error(INTERRUPT_FAILURE);
                observeSettlement(id, entry);
            }
            finally {
                if (timer)
                    clearTimeout(timer);
            }
        }
        catch {
            entry.failed = true;
            throw new Error(INTERRUPT_FAILURE);
        }
        finally {
            entry.inflight -= 1;
            maybeRelease(id, entry);
        }
    };
    try {
        for (const kind of ["context", "compaction", "generate", "title", "http.request", "experimental.ws.send"]) {
            registrations.push(await session.hook(kind, async (event) => {
                try {
                    const id = event.sessionID;
                    if (globallyClosed || !validSessionID(id) || quarantined.has(id))
                        throw new Error();
                }
                catch {
                    throw new Error(INTERRUPT_FAILURE);
                }
            }));
        }
        registrations.push(await tool.hook("execute.after", async (event) => {
            let status;
            let original;
            try {
                status = event.status;
                if (status === "error")
                    original = event.error;
            }
            catch {
                globallyClosed = true;
                throw new Error(REDACTION_FAILURE);
            }
            if (status === "error") {
                if (cancellationKind(original) !== "other")
                    return interrupt(event);
                try {
                    event.error = createToolError(await safeErrorMessage(original, redactor));
                }
                catch {
                    throw new Error(REDACTION_FAILURE);
                }
                return;
            }
            if (status !== "completed")
                return interrupt(event);
            try {
                const wrapper = { result: event.result };
                await redactor.redactMutableValueAsync(wrapper);
                event.result = wrapper.result;
            }
            catch {
                throw new Error(REDACTION_FAILURE);
            }
        }));
    }
    catch {
        await Promise.allSettled(registrations.map(async (registration) => registration.dispose()));
        throw new Error("Unable to register V2 tool-output redaction");
    }
    return async () => {
        await Promise.allSettled(registrations.map(async (registration) => registration.dispose()));
    };
}
