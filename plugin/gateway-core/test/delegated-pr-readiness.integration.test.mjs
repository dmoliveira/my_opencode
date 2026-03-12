import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { getRecentDelegationOutcomes } from "../dist/hooks/shared/delegation-runtime-state.js"

test("integration: delegated task completion, validation evidence, DONE proof, and PR readiness stay consistent", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-delegated-pr-readiness-"))
  try {
    execSync("git init -b feature", { cwd: directory, stdio: ["ignore", "pipe", "pipe"] })

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: [
            "delegation-concurrency-guard",
            "subagent-lifecycle-supervisor",
            "subagent-telemetry-timeline",
            "validation-evidence-ledger",
            "done-proof-enforcer",
            "pr-readiness-guard",
          ],
          disabled: [],
        },
        delegationConcurrencyGuard: {
          enabled: true,
          maxTotalConcurrent: 1,
          maxExpensiveConcurrent: 1,
          maxDeepConcurrent: 1,
          maxCriticalConcurrent: 1,
          staleReservationMs: 60000,
        },
        subagentLifecycleSupervisor: {
          enabled: true,
          maxRetriesPerSession: 3,
          staleRunningMs: 60000,
          blockOnExhausted: true,
        },
        subagentTelemetryTimeline: {
          enabled: true,
          maxTimelineEntries: 100,
          persistState: false,
          stateFile: ".opencode/test-runtime-state.json",
          stateMaxEntries: 100,
        },
        validationEvidenceLedger: {
          enabled: true,
        },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["lint", "test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
        prReadinessGuard: {
          enabled: true,
          requireCleanWorktree: false,
          requireValidationEvidence: true,
          requiredMarkers: ["lint", "test"],
        },
      },
    })

    const sessionID = "session-e2e-pr-flow"
    const beforeOutput = {
      args: {
        subagent_type: "reviewer",
        category: "critical",
        prompt: "[DELEGATION TRACE e2e-pr-flow] review branch readiness",
      },
    }
    await plugin["tool.execute.before"](
      { tool: "task", sessionID },
      beforeOutput,
    )

    await plugin.event({
      event: {
        type: "session.created",
        properties: {
          info: {
            id: "child-e2e-pr-flow-1",
            parentID: sessionID,
            title: "[DELEGATION TRACE e2e-pr-flow] reviewer child",
            metadata: {
              gateway: {
                delegation: beforeOutput.metadata?.gateway?.delegation,
              },
            },
          },
        },
      },
    })
    await plugin.event({
      event: {
        type: "session.idle",
        properties: {
          sessionID: "child-e2e-pr-flow-1",
        },
      },
    })

    const delegationRecord = getRecentDelegationOutcomes(60000)
      .filter((item) => item.sessionId === sessionID && item.traceId === "e2e-pr-flow")
      .at(-1)
    assert.ok(delegationRecord)
    assert.equal(delegationRecord.status, "completed")

    await plugin["tool.execute.before"](
      { tool: "task", sessionID },
      {
        args: {
          subagent_type: "explore",
          category: "quick",
          prompt: "follow-up after delegated completion",
        },
      },
    )

    const prematureDone = { output: { stdout: "wrap up\n<promise>DONE</promise>", stderr: "" } }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID }, prematureDone)
    assert.match(String(prematureDone.output.stdout), /PENDING_VALIDATION/)

    await assert.rejects(
      () =>
        plugin["tool.execute.before"](
          { tool: "bash", sessionID },
          { args: { command: 'gh pr create --title "x" --body "## Summary\n- x\n## Validation\n- pending"' } },
        ),
      /Missing validation evidence/i,
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID },
      { args: { command: "npm run lint" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID },
      { output: { stdout: "lint passed", stderr: "" } },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID },
      { args: { command: "node --test plugin/gateway-core/test/pr-readiness-guard-hook.test.mjs" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID },
      { output: { stdout: "tests passed", stderr: "" } },
    )

    const validatedDone = { output: { stdout: "ready\n<promise>DONE</promise>", stderr: "" } }
    await plugin["tool.execute.after"]({ tool: "bash", sessionID }, validatedDone)
    assert.doesNotMatch(String(validatedDone.output.stdout), /PENDING_VALIDATION/)
    assert.match(String(validatedDone.output.stdout), /<promise>DONE<\/promise>/)

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID },
      {
        args: {
          command:
            'gh pr create --title "Structured output e2e" --body "## Summary\n- verified\n## Validation\n- npm run lint\n- node --test plugin/gateway-core/test/pr-readiness-guard-hook.test.mjs"',
        },
      },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
