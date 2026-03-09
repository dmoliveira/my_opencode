#!/usr/bin/env node

import { readFileSync, writeFileSync } from "node:fs"
import { resolve } from "node:path"

import { loadGatewayConfig, loadGatewayConfigSource } from "../plugin/gateway-core/dist/config/load.js"
import {
  createLlmDecisionRuntime,
  resolveLlmDecisionRuntimeConfigForHook,
} from "../plugin/gateway-core/dist/hooks/shared/llm-decision-runtime.js"
import {
  renderLlmScenarioMarkdown,
  summarizeLlmScenarioResults,
} from "../plugin/gateway-core/dist/audit/llm-scenario-report.js"

const args = process.argv.slice(2)
const markdownIndex = args.indexOf("--markdown-out")
const markdownOut = markdownIndex >= 0 ? resolve(args[markdownIndex + 1] || "") : ""
const fixtureArg = args.find((arg, index) => arg && index !== markdownIndex && index !== markdownIndex + 1 && !arg.startsWith("--"))
const fixturePath = fixtureArg
  ? resolve(fixtureArg)
  : resolve("docs/plan/status/in_progress/llm-scenario-fixtures.json")

const fixtures = JSON.parse(readFileSync(fixturePath, "utf-8"))
const repoConfig = JSON.parse(readFileSync(resolve("opencode.json"), "utf-8"))
const cfg = loadGatewayConfig(loadGatewayConfigSource(process.cwd(), repoConfig))

const results = []
for (const fixture of fixtures) {
  const runtime = createLlmDecisionRuntime({
    directory: process.cwd(),
    config: resolveLlmDecisionRuntimeConfigForHook(cfg.llmDecisionRuntime, fixture.hookId),
  })
  const result = await runtime.decide({
    hookId: fixture.hookId,
    sessionId: `scenario-${fixture.id}`,
    templateId: `${fixture.hookId}-${fixture.id}`,
    instruction: fixture.instruction,
    context: fixture.context,
    allowedChars: fixture.allowedChars,
    decisionMeaning: fixture.decisionMeaning,
  })
  results.push({
    id: fixture.id,
    hookId: fixture.hookId,
    requestType: fixture.requestType,
    description: fixture.description,
    expectedChar: fixture.expectedChar,
    expectedMeaning: fixture.expectedMeaning,
    actualChar: result.char,
    actualMeaning: result.meaning,
    accepted: result.accepted,
    correct: result.accepted && result.char === fixture.expectedChar,
    durationMs: result.durationMs,
    raw: result.raw,
  })
}

const summary = summarizeLlmScenarioResults(results)
const payload = { summary, results }
console.log(JSON.stringify(payload, null, 2))
if (markdownOut) {
  writeFileSync(markdownOut, renderLlmScenarioMarkdown(summary, results), "utf-8")
}
