import { randomBytes } from "node:crypto"
import { mkdtempSync, realpathSync, rmSync } from "node:fs"
import { createServer, type Socket } from "node:net"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { PERMIT_MS } from "./protocol.js"
import type { MetadataBinding } from "./protocol.js"
import { createHash } from "node:crypto"

export interface Capability { path: string; nonce: string; until: number; close: () => void }

/** Private, one-shot host handshake. A CLI flag/receipt cannot mint a setup permit. */
export async function capability(fingerprint: string, recheck: () => void): Promise<Capability> {
  return privateCapability(fingerprint, recheck, "setup")
}

export function metadataCapabilityBinding(binding: MetadataBinding): string {
  return createHash("sha256").update(JSON.stringify(["metadata-promotion-v1", binding.phase, binding.session, binding.call,
    binding.issuer, binding.root, binding.fingerprint, binding.nonce, binding.original, binding.candidate])).digest("hex")
}

export async function metadataCapability(binding: MetadataBinding, recheck: () => void): Promise<Capability> {
  if (binding.phase !== "migrate") throw new Error("metadata_capability_invalid")
  return privateCapability(metadataCapabilityBinding(binding), recheck, "metadata-promotion-v1")
}

async function privateCapability(fingerprint: string, recheck: () => void, operation: "setup" | "metadata-promotion-v1"): Promise<Capability> {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "dependency-authority-")))
  const path = join(directory, "permit.sock")
  const nonce = randomBytes(32).toString("hex")
  let spent = false
  const clients = new Set<Socket>()
  const server = createServer({ allowHalfOpen: true }, (client) => {
    if (spent || clients.size >= 2) { client.destroy(); return }
    clients.add(client)
    client.on("close", () => clients.delete(client))
    client.on("error", () => client.destroy())
    client.setTimeout(5000, () => { client.destroy(); close() })
    let data = ""
    client.on("data", (chunk) => {
      data += chunk.toString()
      if (data.length > 256) { client.destroy(); close() }
    })
    client.on("end", () => {
      if (spent) { client.destroy(); return }
      spent = true
      try {
        const request = operation === "setup" ? { nonce, fingerprint } : { operation, nonce, fingerprint }
        if (data !== JSON.stringify(request) + "\n") throw new Error("capability_invalid")
        recheck()
        client.end("authorized\n")
        server.close()
        clearTimeout(timer)
        rmSync(directory, { recursive: true, force: true })
      } catch { close() }
    })
  })
  const close = (): void => {
    spent = true
    clearTimeout(timer)
    for (const client of clients) client.destroy()
    server.close()
    rmSync(directory, { recursive: true, force: true })
  }
  const until = Date.now() + PERMIT_MS
  const timer = setTimeout(close, PERMIT_MS)
  timer.unref()
  server.unref()
  try {
    await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(path, resolve) })
  } catch (error) { close(); throw error }
  return { path, nonce, until, close }
}
