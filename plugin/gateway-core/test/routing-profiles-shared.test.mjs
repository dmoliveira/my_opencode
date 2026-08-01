import assert from "node:assert/strict"
import test from "node:test"

import {
  downgradeRoutingCategory,
  downgradeRoutingModel,
  routingModelForCategory,
} from "../dist/hooks/shared/routing-profiles.js"

test("routing profiles use the intended GPT-5.6 tiers", () => {
  assert.equal(routingModelForCategory("quick"), "openai/gpt-5.6-luna")
  assert.equal(routingModelForCategory("balanced"), "openai/gpt-5.6-terra")
  assert.equal(routingModelForCategory("deep"), "openai/gpt-5.6-sol")
  assert.equal(routingModelForCategory("critical"), "openai/gpt-5.6-sol")
  assert.equal(routingModelForCategory("visual"), "openai/gpt-5.6-terra")
  assert.equal(routingModelForCategory("writing"), "openai/gpt-5.4")
})

test("routing downgrade policy moves between GPT-5.6 tiers", () => {
  assert.equal(downgradeRoutingCategory("critical"), "balanced")
  assert.equal(downgradeRoutingCategory("deep"), "balanced")
  assert.equal(downgradeRoutingModel("openai/gpt-5.6-sol", "critical"), "openai/gpt-5.6-terra")
  assert.equal(downgradeRoutingModel("openai/gpt-5.6-terra", "balanced"), "openai/gpt-5.6-luna")
  assert.equal(downgradeRoutingModel("openai/gpt-5.4", "writing"), "openai/gpt-5.6-terra")
})
