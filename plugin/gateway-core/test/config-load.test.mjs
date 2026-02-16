import assert from "node:assert/strict"
import test from "node:test"

import { loadGatewayConfig } from "../dist/config/load.js"

test("loadGatewayConfig keeps defaults for new safety guard knobs", () => {
  const config = loadGatewayConfig({})
  assert.equal(config.secretCommitGuard.enabled, true)
  assert.equal(config.prBodyEvidenceGuard.requireSummarySection, true)
  assert.equal(config.parallelWriterConflictGuard.maxConcurrentWriters, 2)
  assert.equal(config.postMergeSyncGuard.requireDeleteBranch, true)
})

test("loadGatewayConfig normalizes invalid maxConcurrentWriters", () => {
  const config = loadGatewayConfig({
    parallelWriterConflictGuard: {
      maxConcurrentWriters: 0,
    },
  })
  assert.equal(config.parallelWriterConflictGuard.maxConcurrentWriters, 2)
})
