import type { SecretRedactor } from "../hooks/shared/secret-redaction.js"
import type { Registration, SessionHooks } from "./types.js"

/**
 * Registers the model-context portion of the V2 redaction port. This is not a
 * complete provider boundary: later plugins and raw HTTP/WebSocket hooks can
 * still modify requests. Do not enable this as a standalone security plugin.
 */
export async function registerV2ContextRedaction(
  session: SessionHooks,
  redactor: Pick<SecretRedactor, "redactMutableValueAsync">,
): Promise<() => Promise<void>> {
  const registrations: Registration[] = []
  try {
    for (const kind of ["context", "compaction", "generate", "title"] as const) {
      registrations.push(await session.hook(kind, async (event) => {
        if (!Array.isArray(event.system) || !Array.isArray(event.messages)) {
          throw new Error("invalid V2 model context; refusing unscanned request")
        }
        await redactor.redactMutableValueAsync(event.system)
        await redactor.redactMutableValueAsync(event.messages)
      }))
    }
  } catch (error) {
    await Promise.allSettled(registrations.map((registration) => registration.dispose()))
    throw error
  }
  return async () => {
    await Promise.all(registrations.map((registration) => registration.dispose()))
  }
}

const MAX_REQUEST_BYTES = 16 * 1024 * 1024
const BODY_READ_TIMEOUT_MS = 10_000

async function readBody(request: Request): Promise<string> {
  if (!request.body) throw new Error("V2 provider request has no body; refusing unscanned request")
  const encoding = request.headers.get("content-encoding")?.trim().toLowerCase()
  const contentType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase()
  if ((encoding && encoding !== "identity") || contentType !== "application/json") {
    throw new Error("unsupported V2 provider request encoding; refusing unscanned request")
  }
  const reader = request.clone().body!.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  let timeout: ReturnType<typeof setTimeout> | undefined
  let completed = false
  try {
    const timedOut = new Promise<never>((_, reject) => {
      timeout = setTimeout(() => reject(new Error("V2 provider request body read timed out")), BODY_READ_TIMEOUT_MS)
    })
    while (true) {
      const result = await Promise.race([reader.read(), timedOut])
      if (result.done) break
      size += result.value.byteLength
      if (size > MAX_REQUEST_BYTES) throw new Error("V2 provider request body too large; refusing unscanned request")
      chunks.push(result.value)
    }
    const bytes = new Uint8Array(size)
    let offset = 0
    for (const chunk of chunks) {
      bytes.set(chunk, offset)
      offset += chunk.byteLength
    }
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes)
    completed = true
    return text
  } finally {
    if (timeout) clearTimeout(timeout)
    if (!completed) void reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

async function redactJson(
  text: string,
  redactor: Pick<SecretRedactor, "redactMutableValueAsync">,
): Promise<string> {
  let body: unknown
  try {
    body = JSON.parse(text)
  } catch {
    throw new Error("invalid V2 provider JSON; refusing unscanned request")
  }
  if (!body || typeof body !== "object") {
    throw new Error("invalid V2 provider JSON root; refusing unscanned request")
  }
  const stats = await redactor.redactMutableValueAsync(body)
  return stats.matches === 0 ? text : JSON.stringify(body)
}

/** Experimental final transport scan. It is not a production-ready boundary:
 * later plugin hooks and provider paths not covered by native hooks need review.
 */
export async function registerV2TransportRedaction(
  session: SessionHooks,
  redactor: Pick<SecretRedactor, "redactMutableValueAsync">,
): Promise<() => Promise<void>> {
  const registrations: Registration[] = []
  try {
    registrations.push(await session.hook("http.request", async (event) => {
      const before = await readBody(event.request)
      const after = await redactJson(before, redactor)
      if (after === before) return
      const headers = new Headers(event.request.headers)
      headers.delete("content-length")
      event.request = new Request(event.request, { body: after, headers })
    }))
    registrations.push(await session.hook("experimental.ws.send", async (event) => {
      if (Buffer.byteLength(event.frame, "utf8") > MAX_REQUEST_BYTES) {
        throw new Error("V2 provider frame too large; refusing unscanned request")
      }
      event.frame = await redactJson(event.frame, redactor)
    }))
  } catch (error) {
    await Promise.allSettled(registrations.map((registration) => registration.dispose()))
    throw error
  }
  return async () => {
    await Promise.all(registrations.map((registration) => registration.dispose()))
  }
}
