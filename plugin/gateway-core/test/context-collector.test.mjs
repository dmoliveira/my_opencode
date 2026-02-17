import assert from "node:assert/strict"
import test from "node:test"

import { ContextCollector } from "../dist/hooks/context-injector/collector.js"

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
})
