import { updateGatewayStateDomain } from "../../dist/state/storage.js"
import { existsSync, writeFileSync } from "node:fs"

const [directory, domain, rawCount = "30", readyPath, goPath] = process.argv.slice(2)
const count = Number.parseInt(rawCount, 10)

if (!directory || !["activeLoop", "conciseMode"].includes(domain) || !Number.isFinite(count)) {
  throw new Error("usage: gateway-state-writer.mjs <directory> <domain> <count>")
}

if (readyPath || goPath) {
  if (!readyPath || !goPath) {
    throw new Error("start barrier requires both ready and go paths")
  }
  writeFileSync(readyPath, "ready\n", { mode: 0o600 })
  const deadline = performance.now() + 10_000
  const sleeper = new Int32Array(new SharedArrayBuffer(4))
  while (!existsSync(goPath)) {
    if (performance.now() >= deadline) {
      throw new Error("start barrier timed out")
    }
    Atomics.wait(sleeper, 0, 0, 10)
  }
}

for (let index = 0; index < count; index += 1) {
  const value =
    domain === "activeLoop"
      ? {
          active: true,
          sessionId: "node-writer",
          objective: `objective-${index}`,
          completionMode: "promise",
          completionPromise: "DONE",
          iteration: index,
          maxIterations: count,
          startedAt: "2026-07-27T00:00:00Z",
        }
      : {
          mode: index % 2 ? "lite" : "full",
          source: "node-writer",
          sessionId: "node-session",
          activatedAt: "2026-07-27T00:00:00Z",
          updatedAt: `2026-07-27T00:00:${String(index).padStart(2, "0")}Z`,
        }
  updateGatewayStateDomain(directory, domain, value, {
    mode: "replace",
    rootUpdates: { lastUpdatedAt: "2026-07-27T00:00:00Z" },
  })
}

process.stdout.write(`${JSON.stringify({ result: "PASS", domain, count })}\n`)
