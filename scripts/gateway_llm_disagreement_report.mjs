#!/usr/bin/env node

import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { execFileSync } from "node:child_process"
import { join, resolve } from "node:path"

import {
  buildLlmRolloutReport,
  parseGatewayAuditJsonlWithDiagnostics,
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
const parsedAudit = parseGatewayAuditJsonlWithDiagnostics(text)
const events = parsedAudit.events
if (thresholdsIndex >= 0) {
  if (!thresholdsPath || !existsSync(thresholdsPath)) {
    console.error(`gateway disagreement report: thresholds file not found: ${thresholdsPath || "(missing path)"}`)
    process.exit(1)
  }
}
let thresholds
if (thresholdsPath) {
  try {
    thresholds = JSON.parse(readFileSync(thresholdsPath, "utf-8"))
  } catch (error) {
    console.error(
      `gateway disagreement report: failed to parse thresholds file: ${thresholdsPath}: ${error instanceof Error ? error.message : String(error)}`,
    )
    process.exit(1)
  }
}
const report = buildLlmRolloutReport(events, thresholds)
let branch = ""
try {
  branch = String(
    execFileSync("git", ["branch", "--show-current"], {
      cwd: process.cwd(),
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }),
  ).trim()
} catch {
  branch = ""
}
report.metadata = {
  generatedAt: new Date().toISOString(),
  sourceAuditPath: target,
  worktreePath: process.cwd(),
  branch: branch || undefined,
  invalidLines: parsedAudit.invalidLines,
  sourceAuditShared: !target.startsWith(process.cwd()),
}
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
