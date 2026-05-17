# OpenCode Reliability Review Runbook

Date: 2026-05-16
Status: draft
Mode: reusable / append-only
Branch intent: reliability review, hook+slash validation, long-run autonomy hardening

## Purpose

Use this runbook to re-run a focused OpenCode reliability review across future sessions.

Goals:

1. find where OpenCode still stalls or drifts
2. validate hook + slash-command behavior with short realistic exercises
3. pressure-test long-run autonomy, resume, cleanup, and post-session automation
4. capture evidence in one reusable artifact that can be extended on later runs

Primary concerns for this review batch:

- runtime gets stuck after laptop lock / long idle
- subagent or sub-routine execution can stall without enough recovery
- long autonomous runs still ask the user too often
- auto hook / post-session path may not be firing reliably

## Reuse rule

Do not replace this doc on future runs.

Append a new run entry under `## Run Ledger`, update task status rows, and add new findings/remediations below the existing ones.

## How this runbook is organized

This doc has four connected layers:

1. `Epics + tasks` define what must be covered.
2. `Exercise sets` provide short command-level validation slices.
3. `E2E use cases` validate the system as connected AI ↔ user flows.
4. `Coverage gaps` add deeper diagnostics only when needed.

Use it like this:

- start with the task map
- run the matching exercise set
- promote important slices into E2E use cases
- use coverage-gap checks only when the basic path is unclear

## Canonical loop note

No exact `ailoop` template was found in this repo.

Use the closest local continuity contract instead:

- `/autopilot go|resume|report`
- `/resume smart --json`
- `/continuation-stop --reason "manual checkpoint" --json`
- `/digest run --reason manual`
- `/digest run --reason manual --run-post`
- `/session handoff --json`

This runbook treats that stack as the local AI-loop equivalent for session start, continuation, and close.

## Operator preconditions

Before execution starts:

1. create a dedicated git worktree branch
2. run startup health checks
3. confirm slash-command/plugin surface is available
4. attach work to Codememory epic/task state
5. prefer JSON/quiet output first

Historical prerequisite note from Run 1:

- `oc current`, `oc next`, and `oc queue` timed out on DB connection in this worktree earlier on 2026-05-16
- `make doctor` in the Codememory repo reported sqlite config healthy, so repo/runtime config drift or env drift was suspected
- Run 2 restored usable Codememory access in this worktree; keep `R0` as a verification gate, but do not treat the earlier timeout as the current default state

## Minimal AI communication contract

Use this style during review runs unless clarity would be unsafe:

- short first
- JSON first when cmd supports it
- 1-3 lines on success
- no filler, no thanks, no long recap
- terse ok if not ambiguous
- use stable short tags:
  - inline: `ok`, `warn`, `blk`, `nxt`, `evd`
  - blocker block: `BLK:`, `EVD:`, `NXT:`
- good short words: `cfg`, `val`, `cmd`, `ctx`, `tmp`, `tmux`, `bg`, `rsm`, `post`, `hook`
- if blocked, use:
  - `BLK:` exact blocker
  - `EVD:` file/cmd/error
  - `NXT:` best next action

## Session open / close contract

### Open

Run at session start:

```text
/doctor run
/devtools status
/plugin status
/mcp status
/notify status
/gateway concise status --json
/bg doctor --json
/tmux doctor --json
/session doctor --json
```

Then start or resume the loop:

```text
/resume smart --json
/autopilot go --goal "continue active reliability review" --max-cycles 10 --json
```

### Close

Run at session close:

```text
/digest run --reason manual
/session handoff --json
/digest run --reason manual --run-post
/continuation-stop --reason "manual checkpoint" --json
```

Use `~/.config/opencode/my_opencode/scripts/opencode_session.sh` when testing exit-hook behavior so digest-on-exit and audit behavior are exercised too.

## Epic and task-group map

Use one umbrella epic plus explicit task groups so future runs can extend the same structure.

### Umbrella epic

`R: OpenCode reliability + continuity validation`

### Epic breakdown

| Epic | Name | Goal | Status |
| --- | --- | --- | --- |
| R0 | Preconditions + instrumentation | make runtime, evidence, and tracking usable before review | in_progress |
| R1 | Prior-week struggle review | mine last-week evidence to find where OpenCode stalled, drifted, or asked too much | pending |
| R2 | Session continuity | validate start/resume/close/handoff/stop flow | pending |
| R3 | Hook reliability | validate direct hook behavior plus auto-hook paths | pending |
| R4 | Slash-command validation | validate high-value slash commands with short realistic technical tasks | pending |
| R5 | Long-run autonomy + recovery | validate idle, lock, tmux, bg, subagent, and stale-loop recovery | pending |
| R6 | Low-interruption autonomy | reduce needless user prompts and verify concise independent progress | pending |
| R7 | Cleanup + resource hygiene | make tmux/bg/tmp/config cleanup deterministic | pending |
| R8 | Docs + remediation ledger | keep reusable evidence, findings, fixes, and rerun history | in_progress |

### Task index

| Id | Epic | Task | Goal | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| R0.1 | R0 | Codememory/runtime preflight | restore `oc` usability or document temporary fallback | none | done |
| R0.2 | R0 | Startup instrumentation baseline | confirm doctor/plugin/mcp/notify/gateway/bg/tmux/session health surfaces | R0.1 | in_progress |
| R0.3 | R0 | Evidence sink check | verify digest/session index/memory/artifact paths are writable and discoverable | R0.2 | done |
| R1.1 | R1 | Prior-week evidence gather | review last-week digests, session handoffs, memory, notes, and issue/PR context | R0.3 | pending |
| R1.2 | R1 | Struggle taxonomy | classify failures: lock/idle, subagent stall, over-questioning, orphan state, cleanup drift, hook miss | R1.1 | pending |
| R1.3 | R1 | Reliability priority list | rank top failures by frequency, impact, and reproducibility | R1.2 | pending |
| R2.1 | R2 | Session open path | validate startup health flow and resume entrypoint | R0.2 | pending |
| R2.2 | R2 | Session close path | validate digest, handoff, post-run digest, and continuation-stop | R2.1 | pending |
| R2.3 | R2 | Resume path | validate deterministic resume after manual checkpoint/interruption | R2.2 | pending |
| R2.4 | R2 | Orphan/stale state check | confirm stop/close does not leave fake active loops or broken resume hints | R2.3 | pending |
| R3.1 | R3 | Direct hooks smoke | validate `/hooks status`, `/hooks doctor`, and sample hook runs | R0.2 | pending |
| R3.2 | R3 | Auto/post hook path | validate `/post-session` and wrapper-managed exit behavior | R3.1 | pending |
| R3.3 | R3 | Continuation hook path | validate continuation/reminder behavior around resume/stop loops | R2.3 | pending |
| R3.4 | R3 | Hook failure clarity | verify hook failures are visible, concise, and actionable | R3.1 | pending |
| R4.1 | R4 | Core status commands | validate `/doctor`, `/plugin`, `/mcp`, `/notify`, `/gateway concise`, `/session` | R0.2 | pending |
| R4.2 | R4 | Workflow family | validate `/workflow`, `/delivery`, `/autoflow` on short technical tasks | R4.1 | pending |
| R4.3 | R4 | Autonomous family | validate `/autopilot`, `/resume`, `/continuation-stop`, `/digest` | R2.1 | pending |
| R4.4 | R4 | Runtime support family | validate `/bg`, `/agent-pool`, `/tmux`, `/post-session` cleanup/status paths | R4.1 | pending |
| R4.5 | R4 | Complementary short implementations | use several small task types so command validation is realistic, not synthetic-only | R4.2 | pending |
| R5.1 | R5 | Laptop-lock scenario | run real lock/unlock test and inspect post-unlock state | R2.3 | pending |
| R5.2 | R5 | Idle/tmux continuity | validate detach/idle/resume behavior in tmux-backed flow | R4.4 | pending |
| R5.3 | R5 | Background timeout recovery | validate bg timeout, doctor, read, cleanup | R4.4 | pending |
| R5.4 | R5 | Subagent/subroutine robustness | run bounded subagent-heavy slice and inspect stalls, retries, handoff, and stuck-state signals | R4.3 | pending |
| R5.5 | R5 | Stale-loop recovery | inspect stale-loop expiry, orphan cleanup, and resume guidance after interruption | R5.1 | pending |
| R6.1 | R6 | Low-prompt behavior audit | measure where AI asks too much vs where it should act | R1.2 | pending |
| R6.2 | R6 | Minimal comms conformance | verify AI follows short-form contract without losing clarity | R2.1 | pending |
| R6.3 | R6 | Long independent run | validate bounded multi-cycle run with minimal operator intervention | R4.3 | pending |
| R6.4 | R6 | Guardrail quality | ensure fewer questions do not hide blockers or unsafe actions | R6.3 | pending |
| R7.1 | R7 | Tmux cleanup recipe | standardize safe session naming, doctor, detach, and removal flow | R5.2 | pending |
| R7.2 | R7 | BG cleanup recipe | standardize `bg` queue/runs cleanup after pass/fail/timeout | R5.3 | pending |
| R7.3 | R7 | Temp artifact cleanup | standardize tmp dirs, sandbox files, and retained artifact policy | R4.5 | pending |
| R7.4 | R7 | Config rollback | restore temporary post-session/notify/tmux/gateway changes after tests | R3.2 | pending |
| R8.1 | R8 | Run ledger upkeep | append one run block per execution cycle | none | in_progress |
| R8.2 | R8 | Findings ledger | capture each issue with trigger, impact, evidence, likely cause, fix idea | R1.2 | in_progress |
| R8.3 | R8 | Remediation backlog | turn validated gaps into follow-up fixes or docs changes | R8.2 | in_progress |
| R8.4 | R8 | Rerun expansion policy | keep the doc append-only and safe for future review waves | none | done |

### Codememory naming rule

- epic: `OpenCode reliability + continuity validation`
- task pattern: `<task-id> <short task name>`
- examples: `R0.1 Codememory/runtime preflight`, `R5.4 subagent/subroutine robustness`

### Epic acceptance checks

| Epic | Done when |
| --- | --- |
| R0 | runtime preconditions are verified or explicitly blocked with evidence and fallback |
| R1 | last-week struggle patterns are documented and prioritized |
| R2 | open/resume/close/stop flow is exercised with evidence |
| R3 | direct hooks and auto-hook paths are validated with pass/warn/blk outcomes |
| R4 | major slash-command families are exercised through short real tasks |
| R5 | lock, idle, bg, tmux, subagent, and stale-loop scenarios are tested |
| R6 | AI can run longer with fewer interruptions without hiding blockers |
| R7 | cleanup steps are explicit, repeatable, and verified |
| R8 | this doc contains reusable evidence, findings, and rerun history |

## Task execution details

Use the same evidence shape for every task:

- `aim`: what this task proves
- `run`: shortest command set that exercises it
- `pass`: what success looks like
- `warn/fail`: what to watch for
- `cleanup`: what must be reverted or removed
- `evd`: what to record

### Priority order

Run in this order unless a blocker forces a detour:

1. `R0` preconditions
2. `R1` prior-week review
3. `R2` session continuity
4. `R3` hook reliability
5. `R4` slash-command validation
6. `R5` long-run autonomy + recovery
7. `R6` low-interruption autonomy
8. `R7` cleanup + rollback
9. `R8` findings + rerun ledger

`R8` is continuous. Update it during the run, not only at the end.

### Execution map

Use this table to connect the planning layers.

| Epic | Main task focus | Best exercise sets | Best E2E use cases |
| --- | --- | --- | --- |
| `R0` | baseline health, evidence sinks | A | `UC-01`, `UC-07` |
| `R1` | prior-week struggle review | A, G | `UC-04`, `UC-05`, `UC-07` |
| `R2` | open/resume/close continuity | A, D, F | `UC-01`, `UC-02`, `UC-03`, `UC-07`, `UC-08` |
| `R3` | direct + auto hooks | B, D | `UC-02`, `UC-05` |
| `R4` | slash-command families | C, E, F | `UC-01`, `UC-06`, `UC-08`, `UC-09` |
| `R5` | lock/idle/bg/subagent recovery | E, F, G | `UC-03`, `UC-04`, `UC-05`, `UC-06` |
| `R6` | low-interruption autonomy | A, C | `UC-01`, `UC-05`, `UC-09` |
| `R7` | cleanup + rollback | D, E, F | all use cases |
| `R8` | evidence + backlog + reruns | all | all use cases |

## Related material to inspect during review

Use these only when they help the current slice.

| Material | Use it for |
| --- | --- |
| `docs/quickstart.md` | canonical startup checks and main command surface |
| `docs/operator-playbook.md` | worktree-first flow and command-family intent |
| `docs/command-handbook.md` | command syntax/details when a surface behaves unexpectedly |
| `docs/silent-first-command-defaults.md` | low-noise execution and JSON-first defaults |
| `docs/runtime-db-schema.md` | read-only SQLite investigation of sessions/messages/tool parts |
| `docs/specs/e8-plan-handoff-continuity-mapping.md` | continuity/handoff semantics and resume expectations |
| `docs/upstream-divergence-registry.md` | parity context when local behavior differs from upstream expectations |

### R0 Preconditions + instrumentation

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R0.1` | restore `oc` or document fallback | `oc current`; `oc next`; `oc queue`; `make doctor` in codememory repo | `oc` usable or clearly blocked | connection timeout, backend drift, scope drift | none | failing cmds + doctor result |
| `R0.2` | verify baseline health surfaces | `/doctor run`; `/devtools status`; `/plugin status`; `/mcp status`; `/notify status`; `/gateway concise status --json`; `/bg doctor --json`; `/tmux doctor --json`; `/session doctor --json` | clear healthy/degraded status | missing cmd, broken JSON, contradiction, silent no-op | none | short status note per cmd |
| `R0.3` | verify evidence sinks | `/digest run --reason manual`; `/session list --json`; `/memory doctor --json` | digest/session/memory writable | digest missing, session not indexed, memory DB missing | none | paths, ids, doctor payloads |

### R1 Prior-week struggle review

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R1.1` | gather last-week signals | inspect recent digests, session handoff, relevant memory, issue/PR notes | each complaint area has concrete evidence | anecdotal only, no timestamps, no trace | none | source links/paths |
| `R1.2` | classify failure modes | label findings under `lock/idle`, `subagent stall`, `over-questioning`, `orphan state`, `cleanup drift`, `hook miss`, `resume miss` | each bucket has trigger + impact | vague or overlapping labels | none | updated finding blocks |
| `R1.3` | rank what matters first | score buckets by frequency, pain, reproducibility, fix leverage | top 3-5 risks explicit | priorities not evidence-backed | none | ordered risk list |

### R2 Session continuity

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R2.1` | validate open path | startup checks from `R0.2`; `/resume smart --json` | next action is clear | stale target, resume ambiguity | none | startup snapshot + resume result |
| `R2.2` | validate close path | `/digest run --reason manual`; `/session handoff --json`; `/digest run --reason manual --run-post`; `/continuation-stop --reason "manual checkpoint" --json` | clean digest/handoff/stop | missing digest, weak handoff, active loop left behind | none | digest path + handoff + stop result |
| `R2.3` | validate resume path | short `/autopilot go ...`; stop; `/resume smart --json`; `/autopilot resume --json` or nearest canonical resume surface | resumed state matches pending work | wrong target, lost work, duplicate start | stop loop after test | before/after resume snapshot |
| `R2.4` | validate orphan/stale handling | repeat open → short run → stop → resume; inspect active-loop state | no fake active loop | stale marker, misleading resume, unexplained cleanup mutation | clear test state if supported | status payload + reason codes |

### R3 Hook reliability

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R3.1` | smoke direct hooks | `/hooks status`; `/hooks doctor --json`; sample `/hooks run ...` payloads | predictable status + run behavior | hook mismatch, payload rejection without guidance | none | outputs + result codes |
| `R3.2` | validate auto/post hooks | capture prior `/post-session status`; set command/timeout/run-on; `/post-session enable`; `/digest run --reason manual --run-post`; wrapper session via `opencode_session.sh` | manual + exit-triggered hooks both record outcome | silent skip, command never runs, digest omits result | restore prior post-session config exactly | digest post-session block |
| `R3.3` | validate continuation hooks | short `/autopilot go ...`; `/continuation-stop ...`; `/resume smart --json` | hints match real pending work | generic hints, wrong next step, hidden state | ensure loop stopped | stop + resume outputs |
| `R3.4` | validate hook failure clarity | induce one safe degraded path; inspect reason codes + recovery hints | failure says what broke and what next | vague error, no reason code, no next step | revert trigger | error payload + guidance |

### R4 Slash-command validation

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R4.1` | validate core status cmds | `/doctor`; `/plugin`; `/mcp`; `/notify`; `/gateway concise`; `/session` status/doctor paths | concise coherent health view | conflicting states, noisy output, missing JSON | none | one-line verdict per cmd |
| `R4.2` | validate workflow family | `/workflow validate --file <workflow.json> --json`; `/workflow run --file <workflow.json> --execute --json`; `/autoflow start <plan.md> --json`; optional `/delivery start ... --execute --json` | short real work runs with inspectable state | invalid resume, broken run state, confusing contract | stop/cancel test runs | run ids + artifacts |
| `R4.3` | validate autonomous family | `/autopilot go --goal "continue active reliability review" --max-cycles 3 --json`; `/autopilot report --json`; `/resume smart --json`; `/continuation-stop ...` | bounded loop progresses independently | too many questions, vague report, weak stop hygiene | ensure loop stopped | report snapshot + prompt count |
| `R4.4` | validate support family | `/bg doctor --json`; `/agent-pool doctor --json`; `/tmux doctor --json`; `/post-session status` | health + cleanup options are clear | hidden state, stale jobs, tmux mismatch | clear test jobs/sessions | doctor payloads + cleanup results |
| `R4.5` | validate across task shapes | in a throwaway temp workspace/repo, run one tiny code fix, one tiny docs change, one tiny helper/validation addition | behavior holds across task types | works only in one shape, brittle assumptions | remove or isolate temp artifacts | mini-task summary table |

### R5 Long-run autonomy + recovery

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R5.1` | reproduce laptop-lock case | start bounded work in tmux or bg; lock 2-5 min; unlock; inspect tmux/bg/autopilot/resume/session state | state is recoverable | hidden dead state, false active loop, lost progress | close test sessions/jobs | pre-lock vs post-unlock notes |
| `R5.2` | validate idle/tmux continuity | configure `ai-oc`; run bounded loop in tmux; detach; idle; resume | continuity remains understandable | pane mapping loss, stale target, broken re-entry | kill test tmux session | tmux doctor + resume notes |
| `R5.3` | validate bg timeout recovery | `/bg start -- python3 -c "import time; time.sleep(5)" --timeout-seconds 1`; `/bg list --status running`; `/bg read <job-id>`; `/bg cleanup` | timeout visible and cleanup works | stuck job, unreadable logs, cleanup miss | remove remaining job state | job id + cleanup result |
| `R5.4` | inspect subagent stall mode | run one bounded subagent-heavy slice; watch retries, waits, handoff, result loss | completes or fails with blocker contract | hang after subagent output, missing integration, silent stop | stop stray delegated runs | delegated run summary |
| `R5.5` | validate stale-loop recovery | interrupt a loop; inspect status/report/resume; capture cleanup reason codes | stale state cleared or explained | invisible stale loop, silent cleanup mutation | finalize loop state | reason codes + recovery hints |

### R6 Low-interruption autonomy

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R6.1` | audit over-questioning | review recent runs for unnecessary confirmations vs repo policy | concrete over-questioning patterns listed | subjective or uncounted audit | none | timestamped examples |
| `R6.2` | validate minimal comms | use terse contract during one short validation slice | short but safe/inspectable output | ambiguity, weak blocker detail, long green-path output | none | transcript snippets |
| `R6.3` | validate long independent run | `/autopilot go --goal "continue active reliability review" --max-cycles 10 --json` | multi-cycle progress with low operator touch | minor-decision questions, stalls between obvious steps | stop loop after capture | cycle summary + intervention count |
| `R6.4` | validate guardrail quality | inspect risky/blocked moments for clear `BLK/EVD/NXT` | fewer prompts without hidden risk | silent risk, missing blocker contract | none | blocker-path examples |

### R7 Cleanup + resource hygiene

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R7.1` | standardize tmux cleanup | verify prefix; list active test sessions; close unneeded panes/sessions; `/tmux doctor --json` | only intended sessions remain | stale panes, ambiguous ownership, leftover session | kill test sessions | before/after session list |
| `R7.2` | standardize bg cleanup | inspect jobs; cancel if needed; `/bg cleanup` | no stale test jobs remain | terminal jobs persist, logs orphaned, partial cleanup | remove remaining test jobs | before/after bg state |
| `R7.3` | control temp artifacts | one temp root per run; delete after capture; move retained artifacts into named dir if needed | no unexplained temp debris | scattered temp dirs, missing retained-artifact note | remove leftovers | temp root path + final state |
| `R7.4` | restore config | revert temporary `/post-session`, notify, tmux, gateway tweaks using captured pre-test values | baseline config restored or intentional delta documented | hidden persistent test config | final config restore | before/after config notes |

### R8 Docs + remediation ledger

| Task | aim | run | pass | warn/fail | cleanup | evd |
| --- | --- | --- | --- | --- | --- | --- |
| `R8.1` | keep run ledger current | update `## Run Ledger` after each execution slice | every run traceable | missing entry, merged evidence without date/scope | none | run ledger entry |
| `R8.2` | keep findings reusable | add/update `F-<id>` blocks with trigger, impact, evidence, likely cause, fix idea | findings reusable for later fixes | vague notes, no evidence, duplicate ids | dedupe entries | finding ids |
| `R8.3` | keep remediation actionable | create follow-up fix/docs backlog from confirmed findings | each high-value finding has next action | findings with no owner/next step | merge duplicate backlog items | linked backlog items |
| `R8.4` | keep reruns safe | append new runs/findings/tasks; do not rewrite history | future runs can extend safely | overwritten history, renamed ids without migration note | preserve old ids and add migration notes when needed | append-only history |

## Validation method

Do not try to validate every command in one giant run.

Use short complementary exercises. Each exercise must touch a different failure/recovery path and leave small evidence.

### Exercise set A — startup + continuity

Purpose: verify session open/close path, concise mode, digest, handoff, resume.

1. run startup checks
2. run `/digest run --reason manual`
3. run `/session handoff --json`
4. run `/resume smart --json`
5. run `/autopilot go --goal "continue active reliability review" --max-cycles 3 --json`
6. stop with `/continuation-stop --reason "manual checkpoint" --json`

Expected focus:

- no silent failure in digest/indexing
- clear next-action output
- no orphan active-loop state after stop

### Exercise set B — direct hook validation

Purpose: verify built-in hook command surfaces and expected outputs.

Run:

```text
/hooks status
/hooks doctor --json
/hooks run continuation-reminder --json '{"checklist":["update doc","run checks"]}'
/hooks run truncate-safety --json '{"text":"line1\nline2\nline3","max_lines":2,"max_chars":20}'
/hooks run error-hints --json '{"command":"git status","exit_code":128,"stderr":"fatal: not a git repository"}'
```

Expected focus:

- hook registry healthy
- payload validation clear
- output concise on pass, richer on warn/fail

### Exercise set C — short implementation in temp sandbox

Purpose: test realistic execution without risking repo noise.

Create a temp workspace and do one tiny multi-file change such as:

- add a tiny Python CLI with one arg bugfix
- add a tiny README snippet and matching test note
- add a 10-20 line helper script plus one small validation command

Use one of:

- `/workflow validate --file <workflow.json> --json`
- `/workflow run --file <workflow.json> --execute --json`
- `/autoflow start <plan.md> --json`
- `/delivery start --issue <synthetic-or-real-tracker> --role coder --workflow <workflow.json> --execute --json` only if tracking context exists

Expected focus:

- plan/run/execute path works on short real work
- command summaries stay minimal
- close path captures enough evidence

### Exercise set D — post-session automation

Purpose: verify auto hook / post-session execution.

Run:

```text
/post-session status
/post-session set command python3 /Users/diego/Codes/Projects/my_opencode/scripts/doctor_command.py run --json
/post-session set timeout 120000
/post-session set run-on exit,manual
/post-session enable
/digest run --reason manual --run-post
```

Then launch a short session through:

```bash
~/.config/opencode/my_opencode/scripts/opencode_session.sh
```

Expected focus:

- configured command runs on manual digest and on wrapper-managed exit
- digest JSON records post-session result
- failure path is visible, not silent

### Exercise set E — background + long-run recovery

Purpose: validate independent progress and cleanup.

Run:

```text
/bg doctor --json
/bg start -- python3 -c "import time; time.sleep(5)" --timeout-seconds 1
/bg list --status running
/bg read <job-id>
/bg cleanup
```

Optional follow-up:

```text
/agent-pool health --json
/agent-pool doctor --json
```

Expected focus:

- stale/timeout work is visible
- cleanup removes dead state
- notify/bg integration is inspectable

### Exercise set F — tmux-backed continuation

Purpose: validate long-run continuity when the visible shell goes away.

Run:

```text
/tmux status --json
/tmux doctor --json
/tmux config session-prefix ai-oc
```

Use a named session like `ai-oc-rel-review-<date>`.

Inside tmux, run a short long-lived command or bounded review loop, then:

1. detach
2. wait / idle
3. re-open session state with `/resume smart --json`
4. inspect `/session handoff --json`
5. confirm no stale pane/session confusion

Expected focus:

- tmux session naming stable
- resume can reconnect to useful context
- no orphan pane assumptions after idle

### Exercise set G — manual laptop-lock test

Purpose: validate the user-reported failure mode directly.

This step is manual by design.

1. start a bounded long-running review task in tmux or bg
2. record active commands and session ids
3. lock the laptop for 2-5 minutes
4. unlock
5. run:

```text
/tmux doctor --json
/bg doctor --json
/autopilot report --json
/resume smart --json
/session handoff --json
```

If the run used a workflow file, also run:

```text
/workflow status --json
```

Expected focus:

- no hidden dead state
- resume path points to the real remaining work
- stale-loop cleanup or recovery guidance appears when needed

## Priority validation matrix

Validate these surfaces first.

| Surface | Command(s) | Why |
| --- | --- | --- |
| startup health | `/doctor run`, `/plugin status`, `/mcp status`, `/notify status`, `/gateway concise status --json` | baseline runtime health |
| continuity | `/resume smart --json`, `/autopilot go ... --json`, `/continuation-stop --json`, `/session handoff --json`, `/digest run ...` | AI-loop equivalent |
| hooks | `/hooks status`, `/hooks doctor --json`, `/hooks run ...` | direct hook coverage |
| post-session | `/post-session status`, `set`, `enable`, `/digest ... --run-post` | auto hook concern |
| workflow surface | `/workflow validate|run|resume|stop --json` | deterministic engine path |
| autonomous path | `/autoflow start`, `/autoflow status`, `/autopilot go|report --json` | long autonomous path |
| background runtime | `/bg doctor --json`, `/bg cleanup`, `/agent-pool doctor --json` | independent work + cleanup |
| tmux | `/tmux status --json`, `/tmux doctor --json` | lock/idle continuity |

## Coverage gaps to include during review

The core plan already covers the main risk areas. Add these checks when the review run has time, or when a failure points in that direction.

| Area | Add this | Why |
| --- | --- | --- |
| deeper status diagnostics | `/plugin doctor` when available, `/mcp doctor --json`, `/notify doctor --json`, `/digest doctor --json`, `/session show <id> --json` | move beyond status-only checks when behavior is unclear |
| gateway/hook pipeline | `/gateway status`, runtime hook audit path, event audit file check | useful when auto-hook or continuation behavior looks wrong |
| notification evidence | `/notify inbox --json`, `/notify policy status` | useful when bg/post-session events are not visible to the operator |
| session index quality | `/session search <query> --json`, `/session handoff --launch-cwd <wt> --fork --json` | validates handoff quality, not only presence |
| memory continuity | `/memory find <query> --json`, `/memory recall --json`, optional `/memory promote --source digest --json` | useful when long-run recall or resumability feels weak |
| workflow recovery | `/workflow resume --run-id <id> --execute --json`, `/workflow stop --reason ... --json` | validates deterministic recovery, not only first-run execution |
| delivery handoff | `/delivery handoff --issue <id> --to <target> --json`, `/delivery close --issue <id> --json` | useful if ownership/handoff drift is part of the struggle pattern |
| claims/reservation | `/claims status --json`, `/reservation status --json` | useful when multi-agent overlap or path conflicts appear |
| browser-independent wrapper test | launch `opencode_session.sh` from a non-repo cwd | confirms exit-hook/session wrapper does not depend on repo cwd |

Use these as targeted expansion lanes, not mandatory first-pass gates.

## E2E scenario harness

Use this section when you want to test the runtime as a connected system, not as isolated commands.

Goal:

- simulate short AI ↔ user interaction loops
- force hooks, slash commands, session continuity, and support surfaces to interact
- measure quality, speed, independence, recovery, and evidence quality

### Scenario template

Use this block for each end-to-end use case:

```md
### UC-<id> <name>

- goal:
- user prompt shape:
- setup:
- runtime surfaces:
- flow:
- quality checks:
- speed/independence checks:
- failure signals:
- cleanup:
- evd:
```

### Shared harness rules

For all use cases:

1. use a dedicated linked worktree for the review run
2. use a throwaway temp workspace/repo for implementation exercises unless the scenario requires the real repo
3. prefer one named tmux session per scenario: `ai-oc-uc-<id>`
4. if background jobs are used, record the job id immediately
5. open one run-ledger entry before starting the scenario
6. close with digest + handoff + cleanup

### Shared quality rubric

Track these for every use case:

| Dimension | What to check |
| --- | --- |
| quality | output was correct enough, coherent, and produced usable artifacts |
| speed | runtime moved without long dead gaps or unnecessary retries |
| independence | AI made obvious decisions without over-asking |
| tool access | needed tools/plugins/hooks/resources were usable when expected |
| continuity | stop/resume/handoff state stayed consistent |
| recovery | failures produced actionable next steps |
| cleanup | tmux/bg/tmp/config state was restored cleanly |

### Scenario scorecard

Use a compact score per scenario:

```md
- qlty: pass | warn | fail
- speed: fast | ok | slow
- indep: high | med | low
- rcvry: pass | warn | fail
- tools: ok | partial | blocked
- cleanup: done | partial | missed
```

### Shared SQLite investigation checkpoints

Use read-only inspection when a scenario needs deeper runtime evidence.

Default DB path:

- `~/.local/share/opencode/opencode.db`

Read-only patterns:

```bash
sqlite3 -readonly ~/.local/share/opencode/opencode.db ".tables"
sqlite3 -readonly ~/.local/share/opencode/opencode.db ".schema session"
sqlite3 -readonly ~/.local/share/opencode/opencode.db "SELECT id, directory, title FROM session ORDER BY time_updated DESC LIMIT 20;"
sqlite3 -readonly ~/.local/share/opencode/opencode.db "SELECT p.session_id, json_extract(m.data, '$.role') AS role, json_extract(p.data, '$.type') AS part_type, json_extract(p.data, '$.tool') AS tool_name, datetime(p.time_created / 1000, 'unixepoch') AS created_at FROM part p JOIN message m ON m.id = p.message_id WHERE json_extract(p.data, '$.type') = 'tool' ORDER BY p.time_created DESC LIMIT 20;"
```

Use SQLite inspection to answer:

- did the scenario create the expected session/thread shape?
- which tools actually fired?
- did retries/repeated parts appear before a stall?
- was the handoff/digest sequence written when expected?

## E2E use cases to add to the review

These should be run as reusable templates, not one-off tests.

### UC-01 Short implementation loop

- goal: validate a normal short user request through start → implement → validate → close.
- user prompt shape: "make a small technical improvement and validate it."
- setup: throwaway temp repo/workspace; optional tiny workflow file.
- runtime surfaces: `/doctor`, `/resume`, `/autopilot`, `/workflow` or `/autoflow`, `/digest`, `/session handoff`.
- flow:
  1. startup checks
  2. ask AI for a small bounded change
  3. let AI execute with minimal user follow-up
  4. close with digest/handoff
- quality checks: artifact works; summary is short; evidence exists.
- speed/independence checks: few/no avoidable user questions; no dead gap.
- failure signals: AI stops after planning only; asks user to choose low-risk details; closes without evidence.
- cleanup: remove temp repo/workspace.
- evd: diff, validation result, digest, handoff.

### UC-02 Hook-heavy closeout loop

- goal: validate digest/post-session/continuation paths as a connected closeout flow.
- user prompt shape: "finish this slice, record state, and prepare next resume."
- setup: capture prior `/post-session` config first.
- runtime surfaces: `/post-session`, `/digest`, `/session handoff`, `/continuation-stop`, wrapper session.
- flow:
  1. enable post-session command
  2. run one small task slice
  3. close through digest + run-post + wrapper exit
  4. resume from next session
- quality checks: post hook ran, digest includes result, handoff is actionable.
- speed/independence checks: AI uses closeout surfaces without coaching.
- failure signals: silent hook skip, weak handoff, missing next action.
- cleanup: restore exact prior `/post-session` config.
- evd: digest JSON, handoff output, resumed session behavior.

### UC-03 Tmux continuity loop

- goal: validate long-running visible execution with detach/resume.
- user prompt shape: "keep working independently; I may disappear and come back later."
- setup: tmux session `ai-oc-uc-03`.
- runtime surfaces: `/tmux`, `/autopilot`, `/resume`, `/session handoff`, `/digest`.
- flow:
  1. launch bounded work in tmux
  2. detach
  3. wait/idle
  4. re-open and inspect state
- quality checks: resumed context still makes sense.
- speed/independence checks: work continues without needing user nudges.
- failure signals: pane confusion, stale state, lost next step.
- cleanup: kill tmux test session.
- evd: tmux doctor, resume result, session handoff.

### UC-04 Laptop-lock recovery loop

- goal: reproduce and inspect the operator-reported lock problem.
- user prompt shape: "continue this bounded task; I may lock the laptop."
- setup: tmux or bg based run; record session id + active commands first.
- runtime surfaces: `/tmux`, `/bg`, `/autopilot report`, `/resume`, `/session handoff`.
- flow:
  1. start bounded work
  2. lock laptop 2-5 min
  3. unlock and inspect recovery state
- quality checks: real remaining work is still visible.
- speed/independence checks: runtime recovers without full restart if possible.
- failure signals: false active loop, hidden dead state, lost continuity.
- cleanup: close jobs/sessions.
- evd: pre-lock vs post-unlock notes + SQLite session/tool evidence if needed.

### UC-05 Subagent delegation loop

- goal: validate AI → subagent → integration flow.
- user prompt shape: "investigate, then implement or report clearly."
- setup: choose one bounded task likely to trigger delegation.
- runtime surfaces: subagent path, `/autopilot`, `/resume`, `/session handoff`, optional `/claims` or `/reservation` if coordination matters.
- flow:
  1. run a bounded delegated slice
  2. inspect how results are integrated
  3. resume or close
- quality checks: delegation adds value, not confusion.
- speed/independence checks: no hang after subagent output; no needless bounce back to user.
- failure signals: retry loop, result drop, integration stop, silent stall.
- cleanup: stop stray delegated work if any remains visible.
- evd: delegated output summary, final integration result, SQLite tool/message trail if needed.

### UC-06 Background independent worker loop

- goal: validate that longer work can be offloaded and cleaned up safely.
- user prompt shape: "run this in the background and keep me updated only when needed."
- setup: one short bg command and one timeout/recovery command.
- runtime surfaces: `/bg`, `/agent-pool`, `/notify`, `/digest`.
- flow:
  1. start/enqueue bg work
  2. inspect doctor/list/read
  3. test timeout or failure recovery
  4. cleanup
- quality checks: bg state is inspectable and concise.
- speed/independence checks: independent work does not block foreground unnecessarily.
- failure signals: stale running state, poor logs, cleanup miss.
- cleanup: `/bg cleanup` and verify no stale jobs remain.
- evd: job ids, final state, notify evidence if enabled.

### UC-07 Memory + handoff continuity loop

- goal: validate that a later session can resume from artifacts, not chat memory.
- user prompt shape: "capture what matters, then let another run continue."
- setup: at least two sessions.
- runtime surfaces: `/digest`, `/session handoff`, `/memory find`, `/memory recall`, optional `/memory promote --source digest --json`.
- flow:
  1. first session completes a small slice
  2. capture digest/handoff/memory
  3. second session resumes using those artifacts
- quality checks: second session finds enough context quickly.
- speed/independence checks: low reread cost; little/no need to ask the user again.
- failure signals: weak recall, duplicate rediscovery, missing next action.
- cleanup: none beyond standard closeout.
- evd: session ids, memory ids, resumed outcome.

### UC-08 Workflow recovery loop

- goal: validate deterministic execution after interruption.
- user prompt shape: "run this plan/workflow, then recover if interrupted."
- setup: short workflow/plan with at least one visible checkpoint.
- runtime surfaces: `/workflow validate|run|resume|stop`, `/autoflow`, `/session handoff`, `/digest`.
- flow:
  1. start the workflow/plan
  2. interrupt it safely
  3. resume it
  4. close with evidence
- quality checks: resumed state is deterministic.
- speed/independence checks: recovery path is short and obvious.
- failure signals: replays wrong step, loses state, unclear resume target.
- cleanup: stop/cancel leftover runs.
- evd: run ids, state transitions, final outcome.

### UC-09 Minimal-operator mode loop

- goal: validate low-token, high-agency behavior under terse operator guidance.
- user prompt shape: very short prompts, minimal replies expected.
- setup: concise mode on.
- runtime surfaces: `/gateway concise status --json`, `/autopilot`, `/resume`, `/digest`.
- flow:
  1. run one short bounded task in terse mode
  2. inspect whether AI still makes reasonable defaults
  3. verify blocker contract still appears when needed
- quality checks: concise but still correct.
- speed/independence checks: low back-and-forth.
- failure signals: ambiguity, hidden risk, over-compression.
- cleanup: restore prior concise setting if temporarily changed.
- evd: transcript snippets + blocker-path snippets.

## Recommended scenario bundle

If you want one compact but high-value first wave, run:

1. `UC-01` short implementation loop
2. `UC-02` hook-heavy closeout loop
3. `UC-03` tmux continuity loop
4. `UC-04` laptop-lock recovery loop
5. `UC-05` subagent delegation loop
6. `UC-07` memory + handoff continuity loop

That bundle covers the main hooks, core slash commands, delegation, continuity, cleanup, and later-session investigation.

## First-wave route

If you want one efficient first pass with good diagnostic value, run this route:

1. `R0.1` → `R0.3`
2. Exercise `A`
3. Exercise `B`
4. `UC-01` short implementation loop
5. Exercise `D`
6. `UC-02` hook-heavy closeout loop
7. Exercise `F`
8. `UC-03` tmux continuity loop
9. Exercise `G`
10. `UC-04` laptop-lock recovery loop
11. `UC-05` subagent delegation loop
12. `UC-07` memory + handoff continuity loop
13. `R7` cleanup
14. `R8` ledger + findings + remediation update

This route gives one coherent first wave that covers:

- startup health
- continuity
- direct hooks
- auto/post hooks
- short real work
- tmux continuity
- laptop-lock recovery
- subagent robustness
- later-session resumability

## Cleanup contract

After each exercise batch:

1. close or stop active loops
2. run `/bg cleanup`
3. end or kill tmux sessions no longer needed
4. delete temp dirs/files created only for the test
5. revert temporary post-session commands if they were only for validation
6. run `/digest run --reason manual` if the session produced meaningful evidence

### Tmux cleanup

- keep session prefix stable: `ai-oc-*`
- kill only test sessions created for the batch
- do not leave abandoned panes with stale prompts
- run `/tmux doctor --json` before exit if tmux was used heavily

### Temp workspace cleanup

- prefer one temp root per exercise batch, for example `tmp/opencode-rel-review/<run-id>/`
- remove temp artifacts after evidence is captured
- if a test requires keeping artifacts, move them into a named `artifacts/` subdir and reference them in the run ledger

### Config cleanup

- if `/post-session set command ...` was changed only for the test, restore the previous value
- if notification profiles or tmux config were changed for test-only reasons, restore baseline values
- if plugin/gateway config was modified, record exact before/after in findings

## Evidence rules

For each task group, capture:

1. commands used
2. pass/warn/blk result
3. short evidence snippet or file path
4. cleanup done
5. follow-up fix if needed

Prefer JSON outputs and short summaries over large raw logs.

## Findings template

Use this block per finding:

```md
### F-<id> <short title>

- area:
- trigger:
- expected:
- actual:
- impact:
- evd:
- likely cause:
- fix idea:
- status: open | mitigated | fixed | deferred
```

## Run Ledger

Append one block per future run.

```md
### Run <n> — <date> — <owner>

- scope:
- tasks touched:
- env:
- cmds:
- result: ok | warn | blk
- findings:
- cleanup:
- nxt:
```

### Run 1 — 2026-05-16 — agent

- scope: create reusable reliability review runbook
- tasks touched: R0, R1, R2, R3, R4, R5 planning only
- env: dedicated worktree branch; Codememory runtime unhealthy in repo worktree
- cmds:
  - `git fetch --all --prune --quiet`
  - `git worktree add -b feat/opencode-reliability-validation-review ../my_opencode-wt-opencode-reliability-validation-review HEAD`
  - `oc current`
  - `oc next`
  - `oc queue`
  - `make doctor` in `/Users/diego/Codes/Projects/codememory`
- result: warn
- findings:
  - Codememory repo doctor reports sqlite config healthy
  - repo-local `oc current/next/queue` still fail with connection-pool timeout
  - no exact `ailoop` template found; local equivalent is autopilot/resume/digest/session-handoff stack
- cleanup: none needed beyond keeping work in dedicated worktree
- nxt: recover R0, then execute exercise sets A-G in small validated slices

### Run 2 — 2026-05-16 — agent

- scope: continue same-branch reliability review with resumable improvement ledger and first docs-fix slice
- tasks touched: R0.1 recovery evidence, R8.1 ledger upkeep, R8.2 finding capture, R8.3 first remediation
- env: same dedicated worktree branch; Codememory working again in repo worktree (`task_5`, `session_5`)
- cmds:
  - `git fetch --all --prune --quiet`
  - `oc current`
  - `oc next`
  - `oc queue`
  - `oc add task 'Continue reliability review improvements' --scope 'dmoliveira/my_opencode' --kind docs --priority P1`
  - `oc add session 'continue reliability review improvements' --scope 'dmoliveira/my_opencode' --task 'task_5' --worktree '.' --branch 'feat/opencode-reliability-validation-review'`
  - `git diff --check`
  - `make validate`
- result: ok
- findings:
  - local `docs/validation-policy.md` was missing even though repo startup/review docs referenced it as a local path
  - a root append-only session ledger (`improvements-review-2026-05-16.md`) improves resumability for later AI iterations on this branch
  - Codememory access that was previously timing out is now usable in this worktree, so R0 execution can continue from real task/session state
- cleanup: none
- nxt: continue R0-R2 execution with real command evidence and append new findings/remediations to the shared ledger

### Run 3 — 2026-05-16 — agent

- scope: continue same-branch review by hardening missing local operator-reference docs named by repo instructions
- tasks touched: R0.1 evidence reuse, R8.1 ledger upkeep, R8.2 finding capture, R8.3 docs remediation
- env: same dedicated worktree branch; Codememory still active on `task_5` / `session_5`
- cmds:
  - `git fetch --all --prune --quiet`
  - `oc current`
  - `oc next`
  - `oc queue`
  - `test -f docs/index.md`
  - `test -f docs/github-cli.md`
  - `test -f docs/tooling-quick-ref.md`
  - `test -f docs/orchestration-advanced.md`
  - `test -f docs/iterative-testing-workflow.md`
  - `test -f docs/concise-communication-workflow.md`
  - `git diff --check`
  - `make validate`
- result: ok
- findings:
  - repo instructions referenced multiple local docs that were still missing in this worktree, not just `docs/validation-policy.md`
  - adding compact repo-local reference docs closes startup friction for future AI sessions and reduces dependency on sibling/external lookups
  - runbook status rows were stale after Run 2 and are now aligned with current progress
- cleanup: none
- nxt: validate the new doc pack, then continue with real R0.2-R0.3 command evidence or the next highest-value reliability gap

### Run 4 — 2026-05-16 — agent

- scope: execute R0.2-R0.3 command-equivalent runtime checks and capture baseline health evidence
- tasks touched: R0.2 startup instrumentation baseline, R0.3 evidence sink check, R8.1 ledger upkeep, R8.2 finding capture
- env: same dedicated worktree branch; runtime session id `ses_1d026cf9dffeDJqh15lHxWn06r`
- cmds:
  - `python3 scripts/doctor_command.py run --json`
  - `python3 scripts/devtools_command.py status`
  - `python3 scripts/plugin_command.py status`
  - `python3 scripts/mcp_command.py status`
  - `python3 scripts/notify_command.py status`
  - `python3 scripts/gateway_command.py concise status --json`
  - `python3 scripts/background_task_manager.py doctor --json`
  - `python3 scripts/tmux_command.py doctor --json`
  - `python3 scripts/session_command.py doctor --json`
  - `python3 scripts/session_digest.py run --reason manual`
  - `python3 scripts/session_command.py list --limit 5 --json`
  - `python3 scripts/memory_command.py doctor --json`
  - `python3 scripts/session_command.py repair-stale --json`
- result: warn
- findings:
  - most startup surfaces passed or reported expected disabled/default states
  - `session doctor` failed on one stale delegated-child runtime recovery issue from a 2026-05-15 session outside this branch
  - digest/session-index/shared-memory evidence sinks are writable, so `R0.3` can move to done
  - `repair-stale --json` found one repair candidate and proposed an `--apply` follow-up
- cleanup: none
- nxt: decide whether to apply `session repair-stale --apply --json`, then continue into R1/R2 with the stale-session finding recorded

## Exit criteria for this review campaign

The campaign is done when all are true:

1. R0-R5 are executed or explicitly deferred
2. at least one manual lock test was run
3. post-session hook path was verified with real evidence
4. tmux/bg cleanup was verified
5. each priority surface has pass/warn/blk evidence
6. findings and follow-up fixes are documented in this file or linked docs
