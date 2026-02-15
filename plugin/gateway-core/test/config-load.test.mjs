import assert from "node:assert/strict"
import test from "node:test"

import { loadGatewayConfig } from "../dist/config/load.js"

test("loadGatewayConfig keeps default maxIgnoredCompletionCycles", () => {
  const config = loadGatewayConfig({})
  assert.equal(config.autopilotLoop.maxIgnoredCompletionCycles, 1)
})

test("loadGatewayConfig normalizes maxIgnoredCompletionCycles to positive integer", () => {
  const zeroConfig = loadGatewayConfig({
    autopilotLoop: {
      maxIgnoredCompletionCycles: 0,
    },
  })
  assert.equal(zeroConfig.autopilotLoop.maxIgnoredCompletionCycles, 1)

  const explicitConfig = loadGatewayConfig({
    autopilotLoop: {
      maxIgnoredCompletionCycles: 5,
    },
  })
  assert.equal(explicitConfig.autopilotLoop.maxIgnoredCompletionCycles, 5)
})
