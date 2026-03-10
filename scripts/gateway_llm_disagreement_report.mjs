#!/usr/bin/env node

import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { join, resolve } from "node:path"

import {
  buildLlmRolloutReport,
  parseGatewayAuditJsonl,
  renderLlmRolloutMarkdown,
  summarizeLlmDecisionDisagreements,
} from "../plugin/gateway-core/dist/audit/llm-disagreement-report.js"

const args = process.argv.slice(2)
const markdownIndex = args.indexOf("--markdown-out")
const markdownOut = markdownIndex >= 0 ? resolve(args[markdownIndex + 1] || "") : ""
const thresholdsIndex = args.indexOf("--thresholds")
const thresholdsPath = thresholdsIndex >= 0 ? resolve(args[thresholdsIndex + 1] || "") : ""
const targetArg = args.find(
  (arg, index) =>
    arg &&
    index !== markdownIndex &&
    index !== markdownIndex + 1 &&
    index !== thresholdsIndex &&
    index !== thresholdsIndex + 1 &&
    !arg.startsWith("--"),
)
const target = targetArg ? resolve(targetArg) : join(process.cwd(), ".opencode", "gateway-events.jsonl")

if (!existsSync(target)) {
  console.error(`gateway disagreement report: audit file not found: ${target}`)
  process.exit(1)
}

const text = readFileSync(target, "utf-8")
const events = parseGatewayAuditJsonl(text)
const thresholds = thresholdsPath && existsSync(thresholdsPath)
  ? JSON.parse(readFileSync(thresholdsPath, "utf-8"))
  : undefined
const report = buildLlmRolloutReport(events, thresholds)
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

if (markdownOut) {
  writeFileSync(markdownOut, renderLlmRolloutMarkdown(report), "utf-8")
}
