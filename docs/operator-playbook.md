# Operator Playbook

Canonical operational flows for day-to-day delivery with the current command surface.

## Flow 1: Claim -> Deliver -> Close

```text
/delivery start --issue issue-900 --role coder --workflow workflows/ship.json --execute --json
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
/workflow validate --file workflows/ship.json --json
/workflow run --file workflows/ship.json --execute --json
/workflow resume --run-id wf-YYYYmmddHHMMSS --execute --json
```

Use this when a workflow fails and you need deterministic resume from the last failed step.

## Flow 4: Reconciliation and Hygiene

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
