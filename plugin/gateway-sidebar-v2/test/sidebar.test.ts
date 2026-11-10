import { afterEach, expect, test } from "bun:test"
import { chmodSync, mkdtempSync, mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import plugin from "../src/tui.tsx"
import { watchExecutionStatus } from "../src/status-watcher.ts"

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
})

async function until(predicate: () => boolean) {
  const deadline = Date.now() + 3000
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("timed out waiting for status update")
    await Bun.sleep(20)
  }
}

test("registers only for the verified V2 host and returns the slot disposer", () => {
  const slots: unknown[] = []
  const warnings: unknown[] = []
  const dispose = () => {}
  const context = {
    app: { version: "2.2.6" },
    ui: { slot: (slot: unknown) => { slots.push(slot); return dispose }, toast: { show: (toast: unknown) => warnings.push(toast) } },
  }
  expect(plugin.setup(context as never)).toBe(dispose)
  expect(slots).toHaveLength(1)
  expect((slots[0] as { append: string }).append).toBe("sidebar.content")
  context.app.version = "2.2.7"
  expect(plugin.setup(context as never)).toBeUndefined()
  expect(slots).toHaveLength(1)
  expect(warnings).toHaveLength(1)
})

test("observes a late-created state directory and stops after disposal", async () => {
  const root = mkdtempSync(join(tmpdir(), "gateway-sidebar-v2-"))
  roots.push(root)
  const seen: Array<string | null> = []
  const dispose = watchExecutionStatus(root, (snapshot) => seen.push(snapshot?.sessions["ses-test"]?.last ?? null))
  await until(() => seen.length > 0)
  const directory = join(root, ".opencode")
  mkdirSync(directory, { mode: 0o700 })
  chmodSync(directory, 0o700)
  const file = join(directory, "gateway-core.state.json")
  const write = (last: string) => {
    const temporary = join(directory, ".gateway-core.state.json.test")
    writeFileSync(temporary, JSON.stringify({ executionStatus: { version: 1, sessions: { "ses-test": {
      sessionId: "ses-test", last, next: "Continue", updatedAt: new Date().toISOString(),
    } } } }), { mode: 0o600 })
    renameSync(temporary, file)
  }
  write("Started")
  await until(() => seen.includes("Started"))
  write("Validated")
  await until(() => seen.includes("Validated"))
  dispose()
  const count = seen.length
  write("After disposal")
  await Bun.sleep(100)
  expect(seen).toHaveLength(count)
})
