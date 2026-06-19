import assert from "node:assert/strict"
import test from "node:test"

import {
  downgradeRoutingCategory,
  downgradeRoutingModel,
  routingModelForCategory,
} from "../dist/hooks/shared/routing-profiles.js"

test("routing downgrade policy collapses critical and deep to balanced", () => {
  assert.equal(downgradeRoutingCategory("critical"), "balanced")
  assert.equal(downgradeRoutingCategory("deep"), "balanced")
  assert.equal(routingModelForCategory("balanced"), "openai/gpt-5.4")
  assert.equal(downgradeRoutingModel("openai/gpt-5.4", "critical"), "openai/gpt-5.4")
})
