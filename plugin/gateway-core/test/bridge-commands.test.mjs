import test from "node:test"
import assert from "node:assert/strict"

import {
  canonicalAutopilotCommandName,
  parseAutopilotTemplateCommand,
  parseCompletionMode,
  parseCompletionPromise,
  parseDoneCriteria,
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
  assert.equal(resolveAutopilotAction("autopilot", "start --goal ship"), "start")
  assert.equal(resolveAutopilotAction("autopilot", ""), "start")
  assert.equal(resolveAutopilotAction("autopilot", "stop --reason hold"), "stop")
  assert.equal(resolveAutopilotAction("autopilot-resume", ""), "start")
  assert.equal(resolveAutopilotAction("autopilot-pause", ""), "stop")
  assert.equal(resolveAutopilotAction("autopilot", "status --json"), "none")
  assert.equal(resolveAutopilotAction("autopilot", "report --json"), "none")
  assert.equal(resolveAutopilotAction("autopilot", "doctor --json"), "none")
  assert.equal(resolveAutopilotAction("help", ""), "none")
})

test("canonical autopilot command mapping is identity", () => {
  assert.equal(canonicalAutopilotCommandName("autopilot-go"), "autopilot-go")
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
    REASON_CODES.LOOP_RUNTIME_BOOTSTRAPPED,
    "gateway_loop_runtime_bootstrapped"
  )
  assert.equal(
    REASON_CODES.LOOP_COMPLETION_IGNORED_INCOMPLETE_RUNTIME,
    "gateway_loop_completion_ignored_incomplete_runtime"
  )
  assert.equal(
    REASON_CODES.LOOP_STATE_BRIDGE_IGNORED_IN_PLUGIN_MODE,
    "bridge_state_ignored_in_plugin_mode"
  )
  assert.equal(REASON_CODES.CONTEXT_INJECT_CHAT, "pending_context_injected_chat_message")
  assert.equal(
    REASON_CODES.CONTEXT_INJECT_TRANSFORM,
    "pending_context_injected_messages_transform"
  )
  assert.equal(
    REASON_CODES.CONTEXT_REQUEUED_NO_TEXT_PART,
    "pending_context_requeued_no_text_part"
  )
  assert.equal(
    REASON_CODES.COMPACTION_CONTEXT_ALREADY_PRESENT,
    "compaction_context_already_present"
  )
})

test("command parsers resolve completion and goal defaults", () => {
  assert.equal(parseCompletionMode("--completion-mode objective"), "objective")
  assert.equal(parseCompletionMode("--completion-mode=objective"), "objective")
  assert.equal(parseCompletionMode(""), "promise")
  assert.equal(parseCompletionPromise('--completion-promise "DONE_NOW"', "DONE"), "DONE_NOW")
  assert.equal(parseCompletionPromise("--completion-promise=DONE_NOW", "DONE"), "DONE_NOW")
  assert.equal(parseCompletionPromise("", "DONE"), "DONE")
  assert.equal(parseMaxIterations("--max-iterations 25", 100), 25)
  assert.equal(parseMaxIterations("--max-iterations=25", 100), 25)
  assert.equal(parseMaxIterations("--max-iterations 0", 100), 0)
  assert.equal(parseGoal("--goal=ship --max-budget balanced"), "ship")
  assert.equal(parseGoal('--goal="close checklist" --max-budget balanced'), "close checklist")
  assert.equal(parseGoal('--goal "close checklist" --max-budget balanced'), "close checklist")
  assert.deepEqual(
    parseDoneCriteria('--done-criteria "item 1; item 2; item 3" --scope "**"'),
    ["item 1", "item 2", "item 3"]
  )
  assert.deepEqual(parseDoneCriteria('--done-criteria="item 1; item 2" --scope "**"'), ["item 1", "item 2"])
})
