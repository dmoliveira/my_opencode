#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs"
import { join, resolve } from "node:path"

import {
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
const summary = summarizeLlmDecisionDisagreements(parseGatewayAuditJsonl(text))
console.log(JSON.stringify(summary, null, 2))
