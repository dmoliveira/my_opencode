---
status: done
priority: high
updated: 2026-07-30
---

# Deterministic Stale-Session Diagnosis

## Objective

Complete Codememory `task_27` by making legacy-fallback stale-session queries select the same deterministic latest message and part as indexed scans, and document the difference between structurally evidenced stuck sessions and generic age-based stale history.

## Classification and constraints

- Depth: medium.
- Risk: high because the queries feed destructive repair candidates.
- Use synthetic temporary databases only; never inspect or mutate live history.
- Preserve the existing `(time_created DESC, id DESC)` latest-record oracle.
- Reuse the existing `ROW_NUMBER()` selector idiom; require SQLite 3.25+ as already documented and introduce no newer SQL feature.
- Preserve the current query-only snapshot, limits, public fields, issue types, remediation codes, and repair behavior.
- Do not absorb sibling backup, repair-confirmation, generic-repair, or shared-memory tasks.

## Current gap

The indexed scan and the first legacy parent/child query use stable identifier tie-breaks. The remaining legacy queries use `MAX(time_created)` joins, which can select multiple tied messages or parts and produce duplicate, false, or unstable findings. Legacy result limits also omit stable session/child identifiers from their ordering.

## Behavioral contract

1. Every legacy query selects one latest message per session using `ORDER BY time_created DESC, id DESC`.
2. Every legacy query selects one latest part per message using `ORDER BY time_created DESC, id DESC`.
3. Parent/child findings order by parent update time, parent ID, then child ID, all descending.
4. Single-session targeted and generic findings order by session update time then session ID, both descending.
5. Indexed and forced-fallback scans return equivalent finding identities, selected evidence IDs, generic counts, and capped ordering for equal-timestamp fixtures.
6. Structurally evidenced findings stay in `stuck_findings`; age-only incomplete assistant history stays in `generic_stale_findings` and does not become a confirmed stuck classification.
7. Diagnosis remains read-only and creates no schema objects.
8. Ranking occurs before role, completion, error, tool, or status filtering. Generic rows and the uncapped generic count use the same deterministic joins and predicates.

## Fixture matrix

Each family gets a forced-fallback fixture with positive and negative equal-timestamp winners. The descending-ID winner controls classification; a lower-ID contradictory row cannot create a finding. Raw output order is asserted before any canonical sorting.

| Query family | Tied evidence | Exact assertions |
| --- | --- | --- |
| Parent/child mismatch | Parent and child messages; parent and child parts | One finding per positive candidate, exact parent/child message and parent-part IDs, sentinel child-part projection, and no negative-winner finding. |
| Silent parent after abort | Parent and child messages; parent and child parts | One deterministic abort finding, exact public evidence IDs/error projection, and no duplicate from tied losers. |
| Stale delegated child | Parent and child messages; parent and child parts | One deterministic stale-child finding, exact public evidence IDs/child tool projection, and no false lower-ID classification. |
| Stale running tool | Assistant messages and tool parts | Exact selected message/part IDs and structural membership controlled only by descending IDs. |
| Generic stale rows/count | Assistant messages and latest parts | Exact selected evidence, no structural overlap, no tie-inflated count, uncapped count greater than 20, and exactly 20 rows in session-ID-descending order. |

Parent/child, abort, delegated-child, and running-tool fixtures each contain at least 21 equal-update positive candidates so their independent `LIMIT 20` order is verified using the family-specific stable ID suffixes. Generic coverage does the same while asserting its separate uncapped count.

## Repair-consumer assertions

- A forced-fallback preview contains one deduplicated candidate per structural family with the exact deterministic winner IDs; generic history remains excluded unless its existing opt-in is enabled.
- One scoped stale-running-tool apply creates the existing pre-state backup and mutates only the selected latest message, selected latest part, and owning session. Tied losers and unrelated rows remain byte-equivalent.
- Indexed repair behavior and repair implementation remain unchanged.

## Ordered slices

1. Add the family-specific equal-timestamp fixtures above so every legacy selector and independent result limit fails on current SQL.
2. Replace legacy `MAX(time_created)` joins with deterministic one-row latest-message/latest-part selection and add stable result tie-breaks.
3. Add fallback preview and one scoped-apply mutation boundary test.
4. Update `docs/runtime-db-schema.md` with the evidence classification, uncapped generic count, and stable ordering contract.
5. Run focused, full, review, PR, merge, and cleanup gates.

## Validation and review gates

1. Contract gate: critical plan review approves this bounded scope before production edits.
2. Focused gate: every family fixture fails on current fallback SQL, then indexed and fallback results pass with raw exact selected IDs, disjoint classification, uncapped counts, and each independent top-20 order.
3. Runtime gate: `python3 -m py_compile scripts/session_command.py tests/test_session_runtime_database.py`, the 27 existing runtime tests plus new cases, and unchanged repair/backup regressions pass. A no-index fixture with at least 100 sessions completes without `runtime_scan_timeout` under the existing 5-second budget. Reviewer finds no query or repair-candidate regression.
4. Ship gate: `git diff --check`, `make validate`, `make selftest`, `make install-test`, pre-commit, independent verification, critical full-diff review, PR CI, and post-merge CI pass.

## Non-goals and sibling reconciliation

- `task_3` lock resilience and `task_7` safe generated savepoint identifiers are already functionally covered and should be reconciled separately.
- Residual backup verification (`task_4`), preview projection (`task_5`), and generic-repair command guidance (`task_6`) remain separate slices.
- Shared-memory lifecycle improvements (`task_28` and `task_29`) and session-index identity (`task_30`) are outside this task.
