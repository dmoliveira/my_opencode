# Operator Playbook

Canonical operational flows for day-to-day delivery with the current command surface.

## Worktree-first rule

- Start every implementation task in a dedicated git worktree branch created from the current root branch.
- Keep the main project folder on `main`; use it for sync/inspection, not for task edits.
- Never `git checkout` or `git switch` the main project folder onto a task branch.
- Protected branches (`main`, `master`) are edit-blocked by default even in linked worktrees, and bash there is limited to inspection, validation, and sync flows.
- Use `docs/parallel-wt-playbook.md` as the checklist before delegating or editing.

## Choose the right surface

- Use `/delivery` as the default day-to-day command for issue ownership, workflow execution, and closeout.
- Use `/workflow` only when you need direct engine validation, resume, or template control beneath `/delivery`.
- Use `/autopilot` for open-ended autonomous execution that is not centered on a workflow file.
- Use `/autoflow` for deterministic execution of a plan artifact; treat legacy `/start-work` references as backend history, not the recommended surface.

## Flow 1: Claim -> Deliver -> Close

```text
git worktree add ../my_opencode-wt-<task> -b feat/<task> HEAD
/workflow template init ship --json
/delivery start --issue issue-900 --role coder --workflow <workflow.json> --execute --json
/delivery status --json
/delivery close --issue issue-900 --json
```

Use this when one owner should complete the work end-to-end.

## Flow 2: Claim -> Handoff -> Accept

```text
/claims claim issue-901 --by agent:orchestrator --json
/claims handoff issue-901 --to human:alex --json
/claims accept-handoff issue-901 --json
```

Use this when ownership transfers between humans/agents.

## Flow 3: Workflow Reliability Loop

```text
/workflow validate --file <workflow.json> --json
/workflow run --file <workflow.json> --execute --json
/workflow resume --run-id wf-YYYYmmddHHMMSS --execute --json
```

Use this when a workflow fails and you need deterministic resume from the last failed step.

## Flow 4: Open-ended autonomous execution

```text
/autopilot go --goal "finish current objective" --json
/continuation-stop --reason "manual checkpoint" --json
```

Use this when the task is not driven by a workflow file and you want one autonomous loop with guardrails.

## Flow 5: Plan artifact execution

```text
/autoflow start <plan.md> --json
/autoflow status --json
/autoflow report --json
```

Use this when work is already captured as a plan file and you want deterministic execution and resume behavior.

## Flow 6: Reconciliation and Hygiene

```text
/daemon tick --claims-hours 24 --json
/claims expire-stale --hours 48 --apply --json
/doctor run
```

Use this to keep stale claims and runtime state from drifting.

## Incident Checklist

```text
/delivery status --json
/workflow status --json
/claims status --json
/agent-pool health --json
/daemon summary --json
/doctor run
```

If an operation fails repeatedly:

1. capture failing command output in JSON
2. run `/doctor run`
3. apply the first listed quick fix
4. re-run the failing command once
