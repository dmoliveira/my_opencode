#!/usr/bin/env node

import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { execFileSync } from "node:child_process"
import { isAbsolute, join, relative, resolve } from "node:path"

import {
  parseTodoContinuationReport,
  renderTodoContinuationMarkdown,
} from "../plugin/gateway-core/dist/audit/todo-continuation-report.js"

const args = process.argv.slice(2)
const markdownIndex = args.indexOf("--markdown-out")
const markdownOut = markdownIndex >= 0 ? resolve(args[markdownIndex + 1] || "") : ""
const markdownValueIndex = markdownIndex >= 0 ? markdownIndex + 1 : -1
const limitIndex = args.indexOf("--limit-sessions")
const sessionLimitRaw = limitIndex >= 0 ? args[limitIndex + 1] || "" : ""
const limitValueIndex = limitIndex >= 0 ? limitIndex + 1 : -1
const sessionLimitParsed = Number.parseInt(sessionLimitRaw, 10)
const sessionLimit = Number.isFinite(sessionLimitParsed) && sessionLimitParsed > 0 ? sessionLimitParsed : 10
const targetArg = args.find(
  (arg, index) =>
    arg &&
    index !== markdownIndex &&
    index !== markdownValueIndex &&
    index !== limitIndex &&
    index !== limitValueIndex &&
    !arg.startsWith("--"),
)
const target = targetArg ? resolve(targetArg) : join(process.cwd(), ".opencode", "gateway-events.jsonl")

if (!existsSync(target)) {
  console.error(`gateway todo continuation report: audit file not found: ${target}`)
  process.exit(1)
}

const text = readFileSync(target, "utf-8")
const parsed = parseTodoContinuationReport(text, { sessionLimit })

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

parsed.report.metadata = {
  generatedAt: new Date().toISOString(),
  sourceAuditPath: target,
  worktreePath: process.cwd(),
  branch: branch || undefined,
  invalidLines: parsed.invalidLines,
  sourceAuditShared: (() => {
    const rel = relative(process.cwd(), target)
    return rel === "" ? false : rel.startsWith("..") || isAbsolute(rel)
  })(),
  sessionLimit,
}

console.log(JSON.stringify(parsed.report, null, 2))

if (markdownOut) {
  writeFileSync(markdownOut, renderTodoContinuationMarkdown(parsed.report), "utf-8")
}
