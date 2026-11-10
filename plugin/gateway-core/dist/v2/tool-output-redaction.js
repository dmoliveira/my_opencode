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
