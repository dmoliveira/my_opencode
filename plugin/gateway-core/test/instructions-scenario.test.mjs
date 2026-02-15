import assert from "node:assert/strict"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { loadGatewayState } from "../dist/state/storage.js"

test("gateway continuation keeps checklist context from autopilot-go style command", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-instructions-scenario-"))
  const runtimePath = join(directory, "autopilot_runtime.json")
  const previousRuntimePath = process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH
  process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH = runtimePath

  const doneCriteria = ["2x + 1", "5x -2", "x^2 + 1", "-2x + 6", "3x + 5"]

  try {
    writeFileSync(
      runtimePath,
      `${JSON.stringify(
        {
          status: "running",
          objective: {
            goal: "process a five-item checklist",
            completion_mode: "promise",
            completion_promise: "DONE",
            done_criteria: doneCriteria,
          },
          progress: {
            completed_cycles: 0,
            pending_cycles: 5,
          },
          blockers: ["execution_evidence_missing"],
        },
        null,
        2,
      )}\n`,
      "utf-8",
    )

    const prompts = []
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["autopilot-loop", "continuation", "safety"],
          disabled: [],
        },
        autopilotLoop: {
          enabled: true,
          maxIterations: 0,
          completionMode: "promise",
          completionPromise: "DONE",
          orphanMaxAgeHours: 12,
        },
      },
      client: {
        session: {
          async messages() {
            return {
              data: [
                {
                  info: { role: "assistant" },
                  parts: [
                    {
                      type: "text",
                      text: "<promise>DONE</promise>\nI still need the five checklist items.",
                    },
                  ],
                },
              ],
            }
          },
          async promptAsync(args) {
            const text = args.body.parts.map((part) => part.text || "").join("\n")
            prompts.push(text)
          },
        },
      },
    })

    const renderedCommand =
      'python3 "$HOME/.config/opencode/my_opencode/scripts/autopilot_command.py" go --goal "process a five-item checklist" --done-criteria "' +
      doneCriteria.join(";") +
      '" --completion-mode promise --json'

    await plugin["tool.execute.before"](
      { tool: "command", sessionID: "session-instructions" },
      { args: { command: renderedCommand } },
    )

    await plugin.event({
      event: {
        type: "session.idle",
        properties: { sessionID: "session-instructions" },
      },
    })

    const state = loadGatewayState(directory)
    assert.equal(state?.activeLoop?.active, true)
    assert.deepEqual(state?.activeLoop?.doneCriteria, doneCriteria)
    assert.equal(prompts.length, 1)
    assert.ok(prompts[0].includes("Do not ask the user for checklist items"))
    for (const item of doneCriteria) {
      assert.ok(prompts[0].includes(item))
    }
  } finally {
    if (previousRuntimePath === undefined) {
      delete process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH
    } else {
      process.env.MY_OPENCODE_AUTOPILOT_RUNTIME_PATH = previousRuntimePath
    }
    rmSync(directory, { recursive: true, force: true })
  }
})
