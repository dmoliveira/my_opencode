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
