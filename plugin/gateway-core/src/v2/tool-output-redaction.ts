import type { SecretRedactor } from "../hooks/shared/secret-redaction.js"
import type { ToolHooks } from "./types.js"

const REDACTION_FAILURE = "Tool output withheld because redaction failed"
const ERROR_WITHHELD = "Tool execution failed; details withheld by gateway"
const UNSAFE_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/
const PERMISSION_DECLINED = "Permission.DeclinedError"
const DECLINED_SCHEMA_BRAND = `~effect/Schema/Class/${PERMISSION_DECLINED}`
const VERIFIED_OPENCODE_VERSION = "2.2.5"

type ToolErrorFactory = (message: string, cause?: unknown) => unknown

function hasOnlyKeys(value: object, expected: readonly PropertyKey[], accessor?: PropertyKey): boolean {
  const keys = Reflect.ownKeys(value)
  if (keys.length !== expected.length || !keys.every((key) => expected.includes(key))) return false
  return keys.every((key) => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)
    if (!descriptor) return false
    return key === accessor ? typeof descriptor.get === "function" && !descriptor.set : "value" in descriptor
  })
}

// OpenCode 2.2.5 uses the cause's class to stop a plain permission rejection.
// Preserve only that type and its tag, never the original cause's data or stack.
function copyPermissionDecline(error: unknown): unknown | undefined {
  try {
    if (!error || typeof error !== "object") return undefined
    const descriptor = Object.getOwnPropertyDescriptor(error, "error")
    const cause = descriptor && "value" in descriptor ? descriptor.value : undefined
    if (!cause || typeof cause !== "object") return undefined
    const tag = Object.getOwnPropertyDescriptor(cause, "_tag")
    if (!tag || !("value" in tag) || tag.value !== PERMISSION_DECLINED) return undefined
    const prototype = Object.getPrototypeOf(cause)
    if (!prototype) return undefined
    // Reject extra properties or accessors that a copied prototype could expose.
    // This exact internal shape was observed in OpenCode 2.2.5 only.
    if (!hasOnlyKeys(prototype, ["constructor"])) return undefined
    const constructor = Object.getOwnPropertyDescriptor(prototype, "constructor")
    if (!constructor || !("value" in constructor) || typeof constructor.value !== "function") return undefined
    const schema = Object.getPrototypeOf(prototype)
    if (!schema) return undefined
    if (!hasOnlyKeys(schema, ["constructor", "name", DECLINED_SCHEMA_BRAND], DECLINED_SCHEMA_BRAND)) return undefined
    const name = Object.getOwnPropertyDescriptor(schema, "name")
    const brand = Object.getOwnPropertyDescriptor(schema, DECLINED_SCHEMA_BRAND)
    if (!name || !("value" in name) || name.value !== PERMISSION_DECLINED || !brand || typeof brand.get !== "function" || brand.set) return undefined
    const schemaBase = Object.getPrototypeOf(schema)
    if (!schemaBase || !hasOnlyKeys(schemaBase, ["constructor", "toJSON"])) return undefined
    const effectBase = Object.getPrototypeOf(schemaBase)
    if (!effectBase || !hasOnlyKeys(effectBase, [
      "constructor", "~effect/Effect", "pipe", "toJSON", "~effect/Effect/identifier",
      "~effect/Effect/evaluate", "~effect/Effect/successCont", "~effect/Effect/failureCont",
      "~effect/Effect/ensureCont", Symbol.for("nodejs.util.inspect.custom"), Symbol.iterator,
    ]) || Object.getPrototypeOf(effectBase) !== Error.prototype) return undefined
    const copy = Object.create(prototype)
    Object.defineProperties(copy, {
      _tag: { value: PERMISSION_DECLINED, enumerable: true },
      name: { value: PERMISSION_DECLINED },
      message: { value: "" },
      stack: { value: "" },
      toString: { value: () => PERMISSION_DECLINED },
      toJSON: { value: () => ({ _tag: PERMISSION_DECLINED }) },
    })
    return copy
  } catch {
    return undefined
  }
}

async function safeErrorMessage(
  error: unknown,
  redactor: Pick<SecretRedactor, "redactMutableValueAsync">,
): Promise<string> {
  try {
    if (!error || (typeof error !== "object" && typeof error !== "function")) return ERROR_WITHHELD
    const descriptor = Object.getOwnPropertyDescriptor(error, "message")
    if (!descriptor || !("value" in descriptor) || typeof descriptor.value !== "string") return ERROR_WITHHELD
    const candidate = { message: descriptor.value }
    await redactor.redactMutableValueAsync(candidate)
    if (typeof candidate.message !== "string" || !candidate.message.trim() || UNSAFE_CONTROL.test(candidate.message)) {
      return ERROR_WITHHELD
    }
    return candidate.message
  } catch {
    return ERROR_WITHHELD
  }
}

/** Experimental output adapter. The factory must create the host's V2 Tool.Error. */
export async function registerV2ToolOutputRedaction(
  tool: ToolHooks,
  redactor: Pick<SecretRedactor, "redactMutableValueAsync">,
  createToolError: ToolErrorFactory,
  runtimeVersion: string,
): Promise<() => Promise<void>> {
  if (typeof createToolError !== "function") throw new Error("V2 Tool.Error factory required")
  if (runtimeVersion !== VERIFIED_OPENCODE_VERSION) throw new Error("V2 tool-output adapter requires verified OpenCode 2.2.5")
  const registration = await tool.hook("execute.after", async (event) => {
    let status: unknown
    try {
      status = event.status
    } catch {
      throw new Error(REDACTION_FAILURE)
    }
    if (status === "error") {
      // Keep the host's control-flow type for a plain rejection without retaining
      // the original error's potentially sensitive message, cause, or metadata.
      let message = ERROR_WITHHELD
      let cause: unknown
      try {
        const failed = event as { error: unknown }
        const original = failed.error
        message = await safeErrorMessage(original, redactor)
        cause = copyPermissionDecline(original)
        failed.error = createToolError(message, cause)
      } catch {
        // Do not surface an exception raised by a host getter or error factory.
        throw new Error(REDACTION_FAILURE)
      }
      return
    }
    if (status !== "completed") throw new Error(REDACTION_FAILURE)
    try {
      const completed = event as { result: unknown }
      const wrapper = { result: completed.result }
      await redactor.redactMutableValueAsync(wrapper)
      completed.result = wrapper.result
    } catch {
      // Never surface an untrusted redactor/assignment error or a partially scanned result.
      throw new Error(REDACTION_FAILURE)
    }
  })
  return () => registration.dispose()
}
