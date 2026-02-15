import test from "node:test"
import assert from "node:assert/strict"

import {
  canonicalAutopilotCommandName,
  parseCompletionMode,
  parseCompletionPromise,
  parseGoal,
  parseMaxIterations,
  parseSlashCommand,
  resolveAutopilotAction,
} from "../dist/bridge/commands.js"

test("parseSlashCommand normalizes command name and args", () => {
  const parsed = parseSlashCommand('/autopilot go --goal "Ship"')
  assert.equal(parsed.name, "autopilot")
  assert.equal(parsed.args, 'go --goal "Ship"')
})

test("resolveAutopilotAction handles start and stop forms", () => {
  assert.equal(resolveAutopilotAction("autopilot", "go --goal ship"), "start")
  assert.equal(resolveAutopilotAction("autopilot", "stop --reason hold"), "stop")
  assert.equal(resolveAutopilotAction("autopilot-resume", ""), "start")
  assert.equal(resolveAutopilotAction("autopilot-pause", ""), "stop")
  assert.equal(resolveAutopilotAction("cancel-ralph", ""), "stop")
  assert.equal(resolveAutopilotAction("help", ""), "none")
})

test("compatibility aliases normalize to canonical autopilot names", () => {
  assert.equal(canonicalAutopilotCommandName("ralph-loop"), "autopilot-go")
  assert.equal(canonicalAutopilotCommandName("cancel-ralph"), "autopilot-stop")
  assert.equal(canonicalAutopilotCommandName("autopilot"), "autopilot")
})

test("command parsers resolve completion and goal defaults", () => {
  assert.equal(parseCompletionMode("--completion-mode objective"), "objective")
  assert.equal(parseCompletionMode(""), "promise")
  assert.equal(parseCompletionPromise('--completion-promise "DONE_NOW"', "DONE"), "DONE_NOW")
  assert.equal(parseCompletionPromise("", "DONE"), "DONE")
  assert.equal(parseMaxIterations("--max-iterations 25", 100), 25)
  assert.equal(parseMaxIterations("--max-iterations 0", 100), 100)
  assert.equal(parseGoal('--goal "close checklist" --max-budget balanced'), "close checklist")
})
