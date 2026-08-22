import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"

import GatewayCorePlugin from "../dist/index.js"
import {
  inspectGitHubPrCreateBody,
  isGitHubPrCreateCommand,
  resolveGitHubPrCreateEvidenceDirectory,
} from "../dist/hooks/shared/github-pr-commands.js"
import { worktreeValidationEvidence } from "../dist/hooks/validation-evidence-ledger/evidence.js"

let callSequence = 0

function createFixture() {
  const directory = mkdtempSync(join(tmpdir(), "gateway-pr-worktree-"))
  const featureDirectory = `${directory}-feature`
  execFileSync("git", ["init", "-q", "-b", "main"], { cwd: directory })
  execFileSync("git", ["config", "user.email", "pr-worktree@example.invalid"], { cwd: directory })
  execFileSync("git", ["config", "user.name", "PR Worktree Test"], { cwd: directory })
  writeFileSync(join(directory, ".gitignore"), ".opencode/*\n", "utf-8")
  writeFileSync(join(directory, "tracked.txt"), "baseline\n", "utf-8")
  execFileSync("git", ["add", ".gitignore", "tracked.txt"], { cwd: directory })
  execFileSync("git", ["commit", "-qm", "fixture"], { cwd: directory })
  execFileSync("git", ["worktree", "add", "-b", "feature/evidence", featureDirectory], { cwd: directory })
  return { directory, featureDirectory, extraWorktrees: [] }
}

function cleanupFixture(fixture) {
  for (const worktree of [...fixture.extraWorktrees, fixture.featureDirectory].reverse()) {
    try {
      execFileSync("git", ["worktree", "remove", "--force", worktree], { cwd: fixture.directory })
    } catch {
      rmSync(worktree, { recursive: true, force: true })
    }
  }
  rmSync(fixture.directory, { recursive: true, force: true })
}

async function recordValidation(plugin, sessionID, command) {
  const callID = `pr-worktree-validation-${++callSequence}`
  const before = { args: { command } }
  await plugin["tool.execute.before"]({ tool: "bash", sessionID, callID }, before)
  await plugin["tool.execute.after"](
    { tool: "bash", sessionID, callID, args: { command: before.args.command } },
    { output: "validation passed", metadata: { exit: 0, output: "validation passed", truncated: false } },
  )
}

test("PR head evidence resolves one local worktree and rejects ambiguous forms", () => {
  const fixture = createFixture()
  try {
    const expected = realpathSync(fixture.featureDirectory)
    for (const command of [
      "gh pr create --head feature/evidence --title x --body x",
      "gh pr create --head=feature/evidence --title x --body x",
      "gh pr create -H feature/evidence --title x --body x",
      "env gh pr create --head feature/evidence --title x --body x",
      "command gh pr create --head feature/evidence --title x --body x",
    ]) {
      assert.equal(resolveGitHubPrCreateEvidenceDirectory(command, fixture.directory), expected, command)
    }
    assert.equal(resolveGitHubPrCreateEvidenceDirectory("gh pr create --title x --body x", fixture.directory), fixture.directory)
    for (const command of [
      "gh --repo owner/repo pr create --head feature/evidence --title x --body x",
      "GH_REPO=owner/repo gh pr create --head feature/evidence --title x --body x",
      "env \"GH_REPO=owner/repo\" gh pr create --head feature/evidence --title x --body x",
      "gh pr create --head feature/evidence --head feature/evidence --title x --body x",
      "gh pr create --head feature/evidence -H feature/evidence --title x --body x",
      "gh pr create --head owner:feature/evidence --title x --body x",
      "gh pr create --head feature/evidence --title x --body x && gh pr create --title y --body y",
      "gh api repos/owner/repo/pulls -X POST -f head=feature/evidence -f base=main",
    ]) {
      assert.equal(resolveGitHubPrCreateEvidenceDirectory(command, fixture.directory), null, command)
    }

    const duplicateDirectory = `${fixture.directory}-duplicate`
    execFileSync("git", ["worktree", "add", "--force", duplicateDirectory, "feature/evidence"], { cwd: fixture.directory })
    fixture.extraWorktrees.push(duplicateDirectory)
    assert.equal(
      resolveGitHubPrCreateEvidenceDirectory("gh pr create --head feature/evidence --title x --body x", fixture.directory),
      null,
    )
  } finally {
    cleanupFixture(fixture)
  }
})

test("PR guards recognize wrapped or compact compound PR commands and fail evidence closed", async () => {
  const fixture = createFixture()
  try {
    const plugin = GatewayCorePlugin({
      directory: fixture.directory,
      config: {
        hooks: { enabled: true, order: ["pr-body-evidence-guard"], disabled: ["pr-readiness-guard"] },
        doneProofEnforcer: {
          enabled: true,
          requiredMarkers: ["test"],
          requireLedgerEvidence: true,
          allowTextFallback: false,
        },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: false,
          requireValidationSection: false,
          requireValidationEvidence: true,
          allowUninspectableBody: false,
        },
      },
    })
    for (const command of [
      "env gh pr create --head feature/evidence --title x --body x",
      "command gh pr create --head feature/evidence --title x --body x",
      "exec gh pr create --head feature/evidence --title x --body x",
      "g\\h pr create --head feature/evidence --title x --body x",
      "g''h pr create --head feature/evidence --title x --body x",
      "bash -c 'gh pr create --head feature/evidence --title x --body x'",
      "bash -c 'gh api repos/owner/repo/pulls -X POST -f head=feature/evidence -f base=main'",
      "gh api graphql -f query='mutation { createPullRequest(input: {}) { pullRequest { id } } }'",
      "gh api graphql -f 'query=mutation { createPullRequest(input: {}) { pullRequest { id } } }'",
      "gh api graphql -fquery='mutation { createPullRequest(input: {}) { pullRequest { id } } }'",
      "gh api graphql -f query='mutation { pr: createPullRequest(input: {}) { pullRequest { id } } }'",
      "gh api graphql -F query=@create-pull-request.graphql",
      "gh api graphql --input create-pull-request.json",
      "gh api graphql -f query='mutation { updateIssue(input: { body: \"#tag\" }) { clientMutationId } createPullRequest(input: {}) { clientMutationId } }'",
      "bash -c 'gh api graphql -f query=\"mutation { createPullRequest(input: {}) { pullRequest { id } } }\"'",
      "nice gh pr create --head feature/evidence --title x --body x",
      "sudo gh pr create --head feature/evidence --title x --body x",
      "(gh pr create --head feature/evidence --title x --body x)",
      "! gh pr create --head feature/evidence --title x --body x",
      "true&&gh pr create --head feature/evidence --title x --body x",
      "echo x;gh pr create --head feature/evidence --title x --body x",
      "bash -c 'gh api repos/owner/repo/pulls -X POST -f head=feature/evidence -f base=main'",
      "true&&gh api repos/owner/repo/pulls --input pr.json",
    ]) {
      assert.equal(isGitHubPrCreateCommand(command), true, command)
      await assert.rejects(
        plugin["tool.execute.before"](
          { tool: "bash", sessionID: "session-pr-wrapper" },
          { args: { command } },
        ),
        /Missing validation evidence/,
        command,
      )
    }
    for (const command of [
      "gh api graphql -f query='query { viewer { login } }'",
      "gh api graphql -f query='mutation { closeIssue(input: {}) { clientMutationId } }'",
      "gh api graphql -f query='query { search(query: \"createPullRequest\", type: ISSUE, first: 1) { issueCount } }'",
      "gh api graphql -f query='mutation { # createPullRequest(input: {})\ncloseIssue(input: {}) { clientMutationId } }'",
      "echo \"gh api graphql -f query='mutation { createPullRequest(input: {}) { clientMutationId } }'\"",
      "echo gh pr create --title x --body x",
    ]) {
      assert.equal(isGitHubPrCreateCommand(command), false, command)
    }
  } finally {
    cleanupFixture(fixture)
  }
})

test("ambient repository overrides require an explicit transparent unset", () => {
  const fixture = createFixture()
  const previousRepository = process.env.GH_REPO
  const previousHost = process.env.GH_HOST
  try {
    process.env.GH_REPO = "owner/other-repository"
    delete process.env.GH_HOST
    assert.equal(
      resolveGitHubPrCreateEvidenceDirectory(
        "gh pr create --head feature/evidence --title x --body x",
        fixture.directory,
      ),
      null,
    )
    assert.equal(
      resolveGitHubPrCreateEvidenceDirectory(
        "env -u GH_REPO gh pr create --head feature/evidence --title x --body x",
        fixture.directory,
      ),
      realpathSync(fixture.featureDirectory),
    )
  } finally {
    if (previousRepository === undefined) {
      delete process.env.GH_REPO
    } else {
      process.env.GH_REPO = previousRepository
    }
    if (previousHost === undefined) {
      delete process.env.GH_HOST
    } else {
      process.env.GH_HOST = previousHost
    }
    cleanupFixture(fixture)
  }
})

test("make -C validation evidence is scoped to the explicit PR head worktree", async () => {
  const fixture = createFixture()
  try {
    const plugin = GatewayCorePlugin({
      directory: fixture.directory,
      config: {
        hooks: {
          enabled: true,
          order: ["validation-evidence-ledger", "pr-body-evidence-guard"],
          disabled: ["pr-readiness-guard"],
        },
        validationEvidenceLedger: { enabled: true },
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
    const sessionID = "session-pr-worktree-evidence"
    await recordValidation(plugin, sessionID, `make -C ${fixture.featureDirectory} validate`)
    assert.equal(worktreeValidationEvidence(fixture.directory).lint, false)
    assert.equal(worktreeValidationEvidence(fixture.featureDirectory).lint, true)
    assert.equal(worktreeValidationEvidence(fixture.featureDirectory).test, true)

    const body = "## Summary\n- item\n## Validation\n- make validate"
    for (const command of [
      `gh pr create --head feature/evidence --title x --body "${body}"`,
      `env gh pr create --head feature/evidence --title x --body "${body}"`,
      `command gh pr create --head feature/evidence --title x --body "${body}"`,
    ]) {
      await plugin["tool.execute.before"](
        { tool: "bash", sessionID },
        { args: { command } },
      )
    }
    await assert.rejects(
      plugin["tool.execute.before"](
        { tool: "bash", sessionID },
        { args: { command: `env "GH_REPO=owner/repo" gh pr create --head feature/evidence --title x --body "${body}"` } },
      ),
      /Missing validation evidence/,
    )
  } finally {
    cleanupFixture(fixture)
  }
})

test("PR body files are read from the invoking worktree", async () => {
  const fixture = createFixture()
  try {
    writeFileSync(join(fixture.directory, "pr.md"), "## Summary\n- item\n## Validation\n- npm test\n", "utf-8")
    writeFileSync(join(fixture.featureDirectory, "pr.md"), "missing required sections\n", "utf-8")
    const plugin = GatewayCorePlugin({
      directory: fixture.directory,
      config: {
        hooks: { enabled: true, order: ["pr-body-evidence-guard"], disabled: ["pr-readiness-guard"] },
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
      { tool: "bash", sessionID: "session-pr-body-file" },
      { args: { command: "gh pr create --head feature/evidence --title x --body-file pr.md" } },
    )
  } finally {
    cleanupFixture(fixture)
  }
})

test("PR body inspection fails closed for duplicate or mixed body sources", () => {
  const fixture = createFixture()
  try {
    writeFileSync(join(fixture.directory, "body.md"), "body from file\n", "utf-8")
    for (const command of [
      "gh pr create --body first --body second --title x",
      "gh pr create --body first --body-file body.md --title x",
      "gh api repos/owner/repo/pulls -X POST -f body=first -f body=second",
      "gh api repos/owner/repo/pulls -X POST -f body=first --input body.md",
    ]) {
      assert.deepEqual(inspectGitHubPrCreateBody(command, fixture.directory), { body: "", inspectable: false }, command)
    }
  } finally {
    cleanupFixture(fixture)
  }
})

test("PR guards fail closed without a session ID when evidence is required", async () => {
  const fixture = createFixture()
  try {
    const commonConfig = {
      doneProofEnforcer: {
        enabled: true,
        requiredMarkers: ["test"],
        requireLedgerEvidence: true,
        allowTextFallback: false,
      },
    }
    const bodyPlugin = GatewayCorePlugin({
      directory: fixture.directory,
      config: {
        ...commonConfig,
        hooks: { enabled: true, order: ["pr-body-evidence-guard"], disabled: ["pr-readiness-guard"] },
        prBodyEvidenceGuard: {
          enabled: true,
          requireSummarySection: false,
          requireValidationSection: false,
          requireValidationEvidence: true,
          allowUninspectableBody: false,
        },
      },
    })
    await assert.rejects(
      bodyPlugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "gh pr create --title x --body x" } }),
      /Missing validation evidence/,
    )

    const readinessPlugin = GatewayCorePlugin({
      directory: fixture.directory,
      config: {
        ...commonConfig,
        hooks: { enabled: true, order: ["pr-readiness-guard"], disabled: [] },
        prReadinessGuard: { enabled: true, requireCleanWorktree: false, requireValidationEvidence: true },
      },
    })
    await assert.rejects(
      readinessPlugin["tool.execute.before"]({ tool: "bash" }, { args: { command: "gh pr create --title x --body x" } }),
      /Missing validation evidence/,
    )
  } finally {
    cleanupFixture(fixture)
  }
})
