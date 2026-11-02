import { randomBytes } from "node:crypto"
import { mkdtempSync, realpathSync, rmSync } from "node:fs"
import { createServer, type Socket } from "node:net"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { PERMIT_MS } from "./protocol.js"

export interface Capability { path: string; nonce: string; until: number; close: () => void }

/** Private, one-shot host handshake. A CLI flag/receipt cannot mint a setup permit. */
export async function capability(fingerprint: string, recheck: () => void): Promise<Capability> {
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
        if (data !== JSON.stringify({ nonce, fingerprint }) + "\n") throw new Error("capability_invalid")
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
