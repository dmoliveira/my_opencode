import assert from "node:assert/strict"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"

test("pr-body-evidence-guard blocks PR create when body is missing required sections", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
        },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: true,
          requireValidationSection: true,
          requireValidationEvidence: false,
          allowUninspectableBody: false,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-pr-body" },
        { args: { command: 'gh pr create --title "x" --body "plain body"' } },
      ),
      /## Summary/,
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard allows PR create with summary and validation sections", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
        },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: true,
          requireValidationSection: true,
          requireValidationEvidence: false,
          allowUninspectableBody: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body" },
      { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- npm test"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard inspects body file content", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  try {
    const bodyPath = join(directory, "pr.md")
    writeFileSync(bodyPath, "## Summary\n- done\n## Validation\n- npm run lint\n", "utf-8")

    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
        },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: true,
          requireValidationSection: true,
          requireValidationEvidence: false,
          allowUninspectableBody: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body" },
      { args: { command: "gh pr create --title x --body-file pr.md" } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard accepts node --test evidence from the ledger", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
        },
        validationEvidenceLedger: {
          enabled: true,
        },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: true,
          requireValidationSection: true,
          requireValidationEvidence: true,
          allowUninspectableBody: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-node-test" },
      { args: { command: "node --test plugin/gateway-core/test/todoread-cadence-reminder-hook.test.mjs" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-body-node-test" },
      { output: "tests passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-node-test" },
      { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- node --test plugin/gateway-core/test/todoread-cadence-reminder-hook.test.mjs"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard applies the same body checks to gh api PR creation", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
        },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: true,
          requireValidationSection: true,
          requireValidationEvidence: false,
          allowUninspectableBody: false,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-pr-body-api-missing" },
        { args: { command: "gh api repos/foo/bar/pulls -X POST -f title=x -f head=feature -f base=main -f 'body=plain body'" } },
      ),
      /## Summary/,
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-api-ok" },
      {
        args: {
          command:
            "gh api repos/foo/bar/pulls -X POST -f title=x -f head=feature -f base=main -f 'body=## Summary\n- item\n## Validation\n- npm test'",
        },
      },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard accepts validation evidence from another session in the same worktree", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
        },
        validationEvidenceLedger: {
          enabled: true,
        },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: true,
          requireValidationSection: true,
          requireValidationEvidence: true,
          allowUninspectableBody: false,
        },
      },
    })

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-a" },
      { args: { command: "node --test plugin/gateway-core/test/pr-body-evidence-guard-hook.test.mjs" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-body-a" },
      { output: "tests passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-b" },
      { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- node --test plugin/gateway-core/test/pr-body-evidence-guard-hook.test.mjs"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard still accepts validation evidence after a blocked PR attempt in the same session", async () => {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  try {
    const plugin = GatewayCorePlugin({
      directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
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
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: true,
          requireValidationSection: true,
          requireValidationEvidence: true,
          allowUninspectableBody: false,
        },
      },
    })

    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID: "session-pr-body-blocked-then-valid" },
        { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- npm test"' } },
      ),
      /Missing validation evidence/,
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-blocked-then-valid" },
      { args: { command: "npm run lint" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-body-blocked-then-valid" },
      { output: "lint passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-blocked-then-valid" },
      { args: { command: "npm test" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-body-blocked-then-valid" },
      { output: "tests passed" },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-blocked-then-valid" },
      { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- npm run lint\n- npm test"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
