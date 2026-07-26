import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import { createPrBodyEvidenceGuardHook } from "../dist/hooks/pr-body-evidence-guard/index.js"

let validationCallSequence = 0

function createGitDirectory() {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-body-"))
  execFileSync("git", ["init", "-q"], { cwd: directory })
  execFileSync("git", ["config", "user.email", "pr-body@example.invalid"], { cwd: directory })
  execFileSync("git", ["config", "user.name", "PR Body Test"], { cwd: directory })
  writeFileSync(join(directory, ".gitignore"), ".opencode/*\n")
  execFileSync("git", ["add", ".gitignore"], { cwd: directory })
  execFileSync("git", ["commit", "-qm", "fixture"], { cwd: directory })
  return directory
}

async function recordValidation(plugin, sessionID, command, output = "") {
  const callID = `pr-body-validation-${++validationCallSequence}`
  const before = { args: { command } }
  await plugin["tool.execute.before"]({ tool: "bash", sessionID, callID }, before)
  await plugin["tool.execute.after"](
    { tool: "bash", sessionID, callID, args: { command: before.args.command } },
    { output, metadata: { exit: 0, output, truncated: false } },
  )
}

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
  const directory = createGitDirectory()
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

    await recordValidation(
      plugin,
      "session-pr-body-node-test",
      "node --test plugin/gateway-core/test/todoread-cadence-reminder-hook.test.mjs",
      "tests passed",
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
  const directory = createGitDirectory()
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

    await recordValidation(
      plugin,
      "session-pr-body-validation-marker",
      "node --test plugin/gateway-core/test/todoread-cadence-reminder-hook.test.mjs",
      "tests passed",
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
  const directory = createGitDirectory()
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

    await recordValidation(
      plugin,
      "session-pr-body-a",
      "node --test plugin/gateway-core/test/pr-body-evidence-guard-hook.test.mjs",
      "tests passed",
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
  const directory = createGitDirectory()
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

    await recordValidation(
      plugin,
      "session-pr-body-make-validate",
      "make validate",
      "validate passed",
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
  const directory = createGitDirectory()
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

    await recordValidation(
      plugin,
      "session-pr-body-uvx-ruff",
      "uvx ruff check .",
      "All checks passed!",
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
