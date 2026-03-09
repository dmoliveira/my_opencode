#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs"
import { join, resolve } from "node:path"

import {
  buildLlmRolloutReport,
  parseGatewayAuditJsonl,
  summarizeLlmDecisionDisagreements,
} from "../plugin/gateway-core/dist/audit/llm-disagreement-report.js"

const target = process.argv[2]
  ? resolve(process.argv[2])
  : join(process.cwd(), ".opencode", "gateway-events.jsonl")

if (!existsSync(target)) {
  console.error(`gateway disagreement report: audit file not found: ${target}`)
  process.exit(1)
}

const text = readFileSync(target, "utf-8")
const events = parseGatewayAuditJsonl(text)
const report = buildLlmRolloutReport(events)
const legacySummary = summarizeLlmDecisionDisagreements(events)
console.log(
  JSON.stringify(
    {
      ...report,
      summary: legacySummary,
    },
    null,
    2,
  ),
)
