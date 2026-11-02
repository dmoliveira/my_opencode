import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, realpathSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { patchFileTargets, createDependencyRiskGuardHook } from "../dist/hooks/dependency-risk-guard/index.js"

const wrap = (body) => `*** Begin Patch\n${body}\n*** End Patch`
const update = (path, body = "@@\n-old\n+new") => wrap(`*** Update File: ${path}\n${body}`)
const protectedName = "synthetic.lock"

const accepted = [
  [wrap("*** Add File: src/demo.txt\n+hello"), ["src/demo.txt"]],
  [wrap("*** Add File: empty.txt"), ["empty.txt"]],
  [wrap("*** Delete File: src/demo.txt"), ["src/demo.txt"]],
  [update("src/demo.txt"), ["src/demo.txt"]],
  [update("old.txt", "*** Move to: new.txt\n@@\n-old\n+new"), ["old.txt", "new.txt"]],
  [wrap("*** Add File: first.txt\n+one\n*** Update File: second.txt\n@@\n-old\n+new\n*** Delete File: third.txt"), ["first.txt", "second.txt", "third.txt"]],
  [update("src/demo.txt", "@@ description synthetic.lock\n synthetic.lock\n-*** Delete File: synthetic.lock\n+*** Update File: synthetic.lock\n *** Move to: synthetic.lock"), ["src/demo.txt"]],
  [wrap("*** Add File: docs/demo.txt\n+*** Begin Patch\n+*** Update File: synthetic.lock\n+*** End Patch"), ["docs/demo.txt"]],
  [update("src/demo.txt", "@@\n-old\n+new\n*** End of File"), ["src/demo.txt"]],
  [" \r\n  *** Begin Patch \r\n*** Update File:  src/demo.txt  \r\n@@\r\n-old\r\n+new\r\n *** End Patch \r\n", ["src/demo.txt"]],
]
for (const [patch, paths] of accepted) {
  test(`native patch targets ${paths.join(", ")} remain separate from hunk content`, () => assert.deepEqual(patchFileTargets(patch), paths))
}

const malformed = [
  "", "*** Update File: demo.txt", "*** Begin Patch\n*** End Patch", "prefix\n" + update("demo.txt"), update("demo.txt") + "\nsuffix",
  wrap("*** Begin Patch\n*** Add File: demo.txt\n+text"),
  "*** Begin Patch\n*** Add File: demo.txt\n+text\n*** End Patch\n*** End Patch",
  wrap("*** Add File: \n+text"), wrap("*** Update File:"), wrap("*** Delete File:"),
  wrap('*** Update File: "demo.txt"\n@@\n-old\n+new'),
  wrap("*** Add File: demo\u0000.txt\n+text"),
  wrap("*** Move to: new.txt"),
  update("old.txt", "\n*** Move to: new.txt\n@@\n-old\n+new"),
  update("old.txt", "*** Move to: \n@@\n-old\n+new"),
  update("old.txt", "*** Move to: first.txt\n*** Move to: second.txt\n@@\n-old\n+new"),
  wrap("*** Delete File: old.txt\n*** Move to: new.txt"),
  wrap("*** Add File: demo.txt\nunprefixed content"),
  wrap("  *** Add File: demo.txt\n+text"),
  update("demo.txt", "@@\n-old\n+new\n*** Unknown directive"),
  wrap("*** End of File"),
  update("demo.txt", "@@\n-old\n+new\n*** End of File\n+more"),
]
for (let i = 0; i < malformed.length; i++) {
  test(`malformed or ambiguous patch ${i} cannot be classified as safe`, () => assert.equal(patchFileTargets(malformed[i]), null))
}

test("patch size limit measures UTF-8 bytes, accepting the exact boundary", () => {
  const start = "*** Begin Patch\n*** Add File: large.txt\n+"
  const end = "\n*** End Patch"
  const available = 4 * 1024 * 1024 - Buffer.byteLength(start + end)
  const patch = start + "é".repeat(Math.floor(available / 2)) + "x".repeat(available % 2) + end
  assert.equal(Buffer.byteLength(patch), 4 * 1024 * 1024)
  assert.deepEqual(patchFileTargets(patch), ["large.txt"])
  assert.equal(patchFileTargets(patch + "é"), null)
})

async function guardPatch(args, denied) {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "synthetic-patch-guard-")))
  try {
    const hook = createDependencyRiskGuardHook({ directory, enabled: true, lockfilePatterns: [protectedName], commandPatterns: [] })
    const result = hook.event("tool.execute.before", { input: { tool: "apply_patch", sessionID: "synthetic-session", callID: "synthetic-call" }, output: { args } })
    if (denied) await assert.rejects(result, /Lockfile\/dependency edits require explicit security validation/)
    else await result
  } finally { rmSync(directory, { recursive: true, force: true }) }
}

test("harmless source patches mentioning protected names are allowed", async () => {
  await guardPatch({ patchText: update("src/demo.txt", "@@\n-old synthetic.lock\n+new synthetic.lock") }, false)
  await guardPatch({ patch: wrap("*** Add File: docs/demo.txt\n+*** Update File: synthetic.lock") }, false)
  await guardPatch({ patchText: update("docs/synthetic.lock.md") }, false)
})

for (const operation of ["Add", "Update", "Delete"]) {
  test(`actual protected ${operation} target remains denied`, async () => {
    const body = operation === "Add" ? "\n+text" : operation === "Update" ? "\n@@\n-old\n+new" : ""
    await guardPatch({ patchText: wrap(`*** ${operation} File: ${protectedName}${body}`) }, true)
  })
}

for (const [source, target] of [[protectedName, "ordinary.txt"], ["ordinary.txt", protectedName]]) {
  test(`both rename endpoints are checked: ${source} to ${target}`, async () => {
    await guardPatch({ patchText: update(source, `*** Move to: ${target}\n@@\n-old\n+new`) }, true)
  })
}

for (const path of ["folder/../synthetic.lock", "folder/synthetic.lock/.", "folder\\synthetic.lock", "SYNTHETIC.LOCK", "synthetic.lock/"]) {
  test(`protected path variant ${path} cannot evade matching`, async () => await guardPatch({ patchText: update(path) }, true))
}

test("mixed safe/protected multi-file patches are denied as a whole", async () => {
  await guardPatch({ patchText: wrap("*** Add File: ordinary.txt\n+text\n*** Delete File: synthetic.lock") }, true)
})

test("malformed patches without protected-name text fail closed", async () => {
  for (const patchText of malformed) await guardPatch({ patchText }, true)
})

test("existing patchText-before-patch argument precedence is preserved", async () => {
  await guardPatch({ patchText: update(protectedName), patch: update("ordinary.txt") }, true)
  await guardPatch({ patchText: update("ordinary.txt"), patch: update(protectedName) }, false)
  await guardPatch({ patchText: "", patch: update("ordinary.txt") }, true)
})
