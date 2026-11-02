import assert from "node:assert/strict"
import test from "node:test"
import { mkdtempSync, realpathSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { authorizeTaskerRead } from "../dist/hooks/tasker-command-gateway/read-policy.js"
import { createResearchAuthoritySigner } from "../dist/hooks/tasker-command-gateway/research-policy.js"

test("read scopes bind actual file targets, reject host paths, traversal and escaping symlinks", () => {
  const temporary = realpathSync(mkdtempSync(join(tmpdir(), "tasker-read-scope-")))
  const root = join(temporary, "workspace")
  try {
    mkdirSync(join(root, "docs"), { recursive: true }); mkdirSync(join(root, "src"))
    writeFileSync(join(root, "docs/a.md"), "Approved")
    writeFileSync(join(root, "src/private.txt"), "Not in the packet")
    writeFileSync(join(temporary, "host.txt"), "Outside worktree")
    const cap = { worktree: root, paths: ["docs/a.md"] }
    const allowed = { filePath: "docs/a.md" }
    assert.equal(authorizeTaskerRead("read", allowed, cap), true)
    assert.equal(allowed.filePath, join(root, "docs/a.md"))
    for (const filePath of [join(temporary, "host.txt"), "../host.txt", "src/private.txt"]) assert.equal(authorizeTaskerRead("read", { filePath }, cap), false)
    assert.equal(authorizeTaskerRead("glob", { path: "docs", pattern: "*.md" }, { worktree: root, paths: ["docs"] }), true)
    symlinkSync(join(temporary, "host.txt"), join(root, "docs/escape"))
    assert.equal(authorizeTaskerRead("read", { filePath: "docs/escape" }, { worktree: root, paths: ["docs"] }), false)
    assert.equal(authorizeTaskerRead("grep", { pattern: "Approved", path: "docs" }, { worktree: root, paths: ["docs"] }), false)
    assert.equal(authorizeTaskerRead("glob", { pattern: "../**", path: root }, { worktree: root, paths: ["."] }), false)
    assert.equal(authorizeTaskerRead("read", { filePath: "docs/a.md" }, { worktree: root, paths: ["docs/*.md"] }), false)
  } finally { rmSync(temporary, { recursive: true, force: true }) }
})
test("network research requests must name an exact declared HTTPS reference", () => {
  const cap = { worktree: process.cwd(), paths: ["https://docs.example.test/reference"] }
  assert.equal(authorizeTaskerRead("webfetch", { url: "https://docs.example.test/reference" }, cap), true)
  for (const url of ["https://other.example.test/reference", "https://docs.example.test/reference?data=private", "http://docs.example.test/reference", "https://user:password@docs.example.test/reference"]) assert.equal(authorizeTaskerRead("webfetch", { url }, cap), false)
  assert.equal(authorizeTaskerRead("websearch", { query: "private contents" }, cap), false)
})
test("a read authority cannot be changed or borrowed from another native parent", () => {
  const signer = createResearchAuthoritySigner()
  const authority = { version: 1, parent: "native-parent", target: "explore", nonce: "owned", worktree: process.cwd(), paths: ["docs"] }
  const signed = signer.issue(authority)
  assert.deepEqual(signer.verify(signed, "native-parent"), authority)
  assert.equal(signer.verify(signed, "other-parent"), null)
  const parts = signed.match(/authority ([^.]+)\.([^\]]+)/)
  const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString())
  payload.paths = ["."]
  const forged = `[Tasker read authority ${Buffer.from(JSON.stringify(payload)).toString("base64url")}.${parts[2]}]`
  assert.equal(signer.verify(forged, "native-parent"), null)
})
