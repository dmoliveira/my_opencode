import assert from "node:assert/strict"
import test from "node:test"

import { ContextCollector } from "../dist/hooks/context-injector/collector.js"

test("context collector getPending returns empty shape for unknown session", () => {
  const collector = new ContextCollector()
  const pending = collector.getPending("missing-session")

  assert.equal(pending.hasContent, false)
  assert.equal(pending.merged, "")
  assert.equal(pending.entries.length, 0)
})

test("context collector dedupes by source and id", () => {
  const collector = new ContextCollector()

  collector.register("session-1", {
    source: "autopilot-loop",
    id: "objective-summary",
    content: "Old summary",
    priority: "high",
  })
  collector.register("session-1", {
    source: "autopilot-loop",
    id: "objective-summary",
    content: "New summary",
    priority: "high",
  })

  const pending = collector.consume("session-1")
  assert.equal(pending.hasContent, true)
  assert.equal(pending.merged, "New summary")
  assert.equal(pending.entries.length, 1)
  assert.equal(pending.entries[0]?.content, "New summary")
})

test("context collector keeps distinct ids from same source", () => {
  const collector = new ContextCollector()

  collector.register("session-2", {
    source: "autopilot-loop",
    id: "objective-summary",
    content: "Goal block",
    priority: "high",
  })
  collector.register("session-2", {
    source: "autopilot-loop",
    id: "done-criteria",
    content: "Done criteria block",
    priority: "high",
  })

  const pending = collector.consume("session-2")
  assert.equal(pending.hasContent, true)
  assert.match(pending.merged, /Goal block/)
  assert.match(pending.merged, /Done criteria block/)
  assert.equal(pending.entries.length, 2)
})

test("context collector tracks metadata in introspection entries", () => {
  const collector = new ContextCollector()

  collector.register("session-3", {
    source: "autopilot-loop",
    id: "objective-summary",
    content: "Summary with metadata",
    priority: "high",
    metadata: { origin: "autopilot", revision: 2 },
  })

  const pending = collector.getPending("session-3")
  assert.equal(pending.hasContent, true)
  assert.equal(pending.entries.length, 1)
  assert.deepEqual(pending.entries[0]?.metadata, { origin: "autopilot", revision: 2 })
})

test("context collector consume clears only the consumed session", () => {
  const collector = new ContextCollector()

  collector.register("session-a", {
    source: "autopilot-loop",
    id: "objective-summary",
    content: "Session A context",
    priority: "high",
  })
  collector.register("session-b", {
    source: "autopilot-loop",
    id: "objective-summary",
    content: "Session B context",
    priority: "high",
  })

  const consumed = collector.consume("session-a")
  assert.equal(consumed.hasContent, true)
  assert.match(consumed.merged, /Session A context/)
  assert.equal(collector.hasPending("session-a"), false)
  assert.equal(collector.hasPending("session-b"), true)
})
