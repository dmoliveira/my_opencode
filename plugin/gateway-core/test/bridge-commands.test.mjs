import test from "node:test"
import assert from "node:assert/strict"

import {
  canonicalAutopilotCommandName,
  parseAutopilotTemplateCommand,
  parseCompletionMode,
  parseCompletionPromise,
  parseGoal,
  parseMaxIterations,
  parseSlashCommand,
  resolveAutopilotAction,
} from "../dist/bridge/commands.js"
import { REASON_CODES } from "../dist/bridge/reason-codes.js"

test("parseSlashCommand normalizes command name and args", () => {
  const parsed = parseSlashCommand('/autopilot go --goal "Ship"')
  assert.equal(parsed.name, "autopilot")
  assert.equal(parsed.args, 'go --goal "Ship"')
})

test("parseAutopilotTemplateCommand maps rendered template command", () => {
  const parsed = parseAutopilotTemplateCommand(
    'python3 "$HOME/.config/opencode/my_opencode/scripts/autopilot_command.py" go --goal "ship" --json'
  )
  assert.ok(parsed)
  assert.equal(parsed?.name, "autopilot-go")
  assert.equal(parsed?.args, '--goal "ship" --json')
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

test("reason code catalog includes runtime routing reasons", () => {
  assert.equal(REASON_CODES.RUNTIME_PLUGIN_READY, "gateway_plugin_ready")
  assert.equal(REASON_CODES.RUNTIME_PLUGIN_DISABLED, "gateway_plugin_disabled")
  assert.equal(
    REASON_CODES.RUNTIME_PLUGIN_RUNTIME_UNAVAILABLE,
    "gateway_plugin_runtime_unavailable"
  )
  assert.equal(REASON_CODES.RUNTIME_PLUGIN_NOT_READY, "gateway_plugin_not_ready")
  assert.equal(REASON_CODES.LOOP_STATE_AVAILABLE, "loop_state_available")
  assert.equal(
    REASON_CODES.LOOP_STATE_BRIDGE_IGNORED_IN_PLUGIN_MODE,
    "bridge_state_ignored_in_plugin_mode"
  )
})

test("command parsers resolve completion and goal defaults", () => {
  assert.equal(parseCompletionMode("--completion-mode objective"), "objective")
  assert.equal(parseCompletionMode(""), "promise")
  assert.equal(parseCompletionPromise('--completion-promise "DONE_NOW"', "DONE"), "DONE_NOW")
  assert.equal(parseCompletionPromise("", "DONE"), "DONE")
  assert.equal(parseMaxIterations("--max-iterations 25", 100), 25)
  assert.equal(parseMaxIterations("--max-iterations 0", 100), 0)
  assert.equal(parseGoal('--goal "close checklist" --max-budget balanced'), "close checklist")
})
