import assert from "node:assert/strict"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createPrBodyEvidenceGuardHook } from "../dist/hooks/pr-body-evidence-guard/index.js"

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

test("pr-body-evidence-guard treats generic validation marker as satisfied by recorded test evidence", async () => {
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
          requiredMarkers: ["validation", "test"],
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
      { tool: "bash", sessionID: "session-pr-body-validation-marker" },
      { args: { command: "node --test plugin/gateway-core/test/todoread-cadence-reminder-hook.test.mjs" } }
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-body-validation-marker" },
      { output: "tests passed" }
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-validation-marker" },
      { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- node --test plugin/gateway-core/test/todoread-cadence-reminder-hook.test.mjs"' } }
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

test("pr-body-evidence-guard accepts make validate lint evidence from structured bash output", async () => {
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
          requiredMarkers: ["lint"],
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
      { tool: "bash", sessionID: "session-pr-body-make-validate" },
      { args: { command: "make validate" } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-body-make-validate" },
      { output: { stdout: "validate passed", stderr: "" } },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-make-validate" },
      { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- make validate"' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard accepts uvx ruff lint evidence from structured bash output", async () => {
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
          requiredMarkers: ["lint"],
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
      { tool: "bash", sessionID: "session-pr-body-uvx-ruff" },
      { args: { command: "uvx ruff check ." } },
    )
    await plugin["tool.execute.after"](
      { tool: "bash", sessionID: "session-pr-body-uvx-ruff" },
      { output: { stdout: "All checks passed!", stderr: "" } },
    )

    await plugin["tool.execute.before"](
      { tool: "bash", sessionID: "session-pr-body-uvx-ruff" },
      { args: { command: 'gh pr create --title "x" --body "## Summary\n- item\n## Validation\n- uvx ruff check ."' } },
    )
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test("pr-body-evidence-guard uses LLM fallback for semantic summary and validation sections", async () => {
  const hook = createPrBodyEvidenceGuardHook({
    directory: process.cwd(),
    enabled: true,
    requireSummarySection: true,
    requireValidationSection: true,
    requireValidationEvidence: false,
    allowUninspectableBody: false,
    requiredMarkers: [],
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "assist",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async (request) => ({
        mode: "assist",
        accepted: true,
        char: "Y",
        raw: "Y",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: request.templateId,
        meaning: request.templateId === "pr-body-summary-v1" ? "summary_present" : "validation_present",
      }),
    },
  })

  await hook.event(
    "tool.execute.before",
    {
      input: { tool: "bash", sessionID: "session-pr-body-llm-1" },
      output: {
        args: {
          command:
            'gh pr create --title "x" --body "## Why this change matters\n- improves routing\n## Checks performed\n- smoke tests passed"',
        },
      },
      directory: process.cwd(),
    },
  )
})

test("pr-body-evidence-guard shadow mode does not accept semantic sections", async () => {
  const hook = createPrBodyEvidenceGuardHook({
    directory: process.cwd(),
    enabled: true,
    requireSummarySection: true,
    requireValidationSection: true,
    requireValidationEvidence: false,
    allowUninspectableBody: false,
    requiredMarkers: [],
    decisionRuntime: {
      config: {
        enabled: true,
        mode: "shadow",
        command: "opencode",
        model: "openai/gpt-5.1-codex-mini",
        timeoutMs: 1000,
        maxPromptChars: 200,
        maxContextChars: 200,
        enableCache: true,
        cacheTtlMs: 10000,
        maxCacheEntries: 8,
      },
      decide: async (request) => ({
        mode: "shadow",
        accepted: true,
        char: "Y",
        raw: "Y",
        durationMs: 1,
        model: "openai/gpt-5.1-codex-mini",
        templateId: request.templateId,
        meaning: request.templateId === "pr-body-summary-v1" ? "summary_present" : "validation_present",
      }),
    },
  })

  await assert.rejects(
    hook.event("tool.execute.before", {
      input: { tool: "bash", sessionID: "session-pr-body-shadow-1" },
      output: {
        args: {
          command:
            'gh pr create --title "x" --body "## Why this change matters\n- improves routing\n## Checks performed\n- smoke tests passed"',
        },
      },
      directory: process.cwd(),
    }),
    /## Summary/,
  )
})
