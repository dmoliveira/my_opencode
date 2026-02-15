# Plugin Gateway Evolution Plan 🧠⚙️

This is the working roadmap for evolving `my_opencode` into a plugin-first gateway (similar power model to `oh-my-opencode`) while keeping command compatibility and operational safety.

Use this as memory + executable checklist.

---

## Decisions (Locked) ✅

- [x] **Core architecture**: TypeScript plugin gateway first.
- [x] **Command interface**: keep slash-command UX stable (`/autopilot` canonical; `/ralph-loop` compatibility alias).
- [x] **Completion model**: support both `promise` and `objective` modes.
- [x] **Default completion mode**: `promise`.
- [x] **Build default agent** remains `build` (not changed).
- [x] **Command bridge language**: **Python** (locked for this migration cycle).

---

## Language choice (final) ⚖️

Final choice for this roadmap:

- **Primary command bridge: Python**
- **Core event/hook engine: TypeScript**
- **No Go/Rust rewrites in this phase**

### Why

| Option | Flexibility | Dev speed | Runtime speed | Best use here |
|---|---:|---:|---:|---|
| Python | High | High | Medium | command bridge + diagnostics + compatibility layer |
| Go | Medium | Medium | High | standalone daemons/ops tooling, less dynamic config ergonomics |
| Rust | Medium | Low/Medium | Very High | performance-critical validators/parsers only |

**Enforcement rule:** do not migrate existing command bridge to Go/Rust during gateway build-out. Re-evaluate only after plugin parity + stabilization.

---

## What is already done 📌

- [x] Promise/objective dual completion modes in `/autopilot`.
- [x] Ralph compatibility aliases (`/ralph-loop`, `/cancel-ralph`) routed to canonical `/autopilot*` semantics.
- [x] Autopilot hook scaffold package (`plugin/autopilot-loop`) with lint/build setup.
- [x] Agent system foundations (contracts, doctor, generated specs).
- [x] Initial roadmap docs and migration notes.
- [x] Command-bridge orphan cleanup telemetry (`orphan_cleanup` + `gateway_orphan_cleanup`) with stale-loop deactivation.

---

## Architecture target (readable + modular) 🏗️

- [ ] `plugin/gateway-core/`
  - [ ] `src/index.ts` (plugin bootstrap + hook registration)
  - [ ] `src/config/schema.ts` (typed config + defaults)
  - [ ] `src/config/load.ts` (config normalization + validation)
  - [ ] `src/state/storage.ts` (session/runtime state)
  - [ ] `src/state/types.ts`
  - [ ] `src/hooks/registry.ts` (enable/disable/order)
  - [ ] `src/hooks/autopilot-loop/*`
  - [ ] `src/hooks/safety/*`
  - [ ] `src/hooks/continuation/*`
  - [ ] `src/bridge/commands.ts` (slash command bridge hooks)
  - [ ] `src/bridge/reason-codes.ts`

- [ ] Keep Python command layer as compatibility shell:
  - [x] `/autopilot*` commands read/write gateway state *(bridge parity layer complete)*
  - [ ] `/doctor*` commands include plugin-hook diagnostics

Design constraints:

- [ ] one module = one responsibility (no giant files)
- [ ] strict TS typing (no `any` in core modules)
- [ ] one-line function comments for exported functions
- [ ] deterministic reason-code catalog shared across hook + command bridge

---

## Borrowed customization ideas from oh-my-opencode 🔌

- [ ] Hook registry with clear lifecycle hooks (`chat.message`, `tool.execute.before/after`, `session.idle`, `session.deleted`, `session.error`)
- [ ] Per-hook feature flags (`enabled`, `order`, `disabled`)
- [ ] Agent override/customization surface (without changing default agent)
- [ ] Deterministic reason codes + remediation hints
- [ ] Loop cancellation and orphan-session cleanup logic
- [ ] Context-aware continuation prompts

Borrow strategy:

- [ ] borrow behavior patterns, not exact implementation coupling
- [ ] keep config surface minimal and readable by default
- [ ] add advanced options only behind explicit flags

---

## Lint/Test checker toggles (easy activate/deactivate) 🧪

### Goal
One command to run strict checks, one command to run fast checks, both configurable.

- [ ] Add profiles in config:
  - [ ] `quality.profile = off|fast|strict`
  - [ ] `quality.ts.lint = true/false`
  - [ ] `quality.ts.typecheck = true/false`
  - [ ] `quality.ts.tests = true/false`
  - [ ] `quality.py.selftest = true/false`

- [ ] Add Make targets:
  - [ ] `make quality-fast`
  - [ ] `make quality-strict`
  - [ ] `make quality-off`

- [ ] Add command aliases:
  - [ ] `/quality profile fast`
  - [ ] `/quality profile strict`
  - [ ] `/quality status --json`

Definition of done for this section:

- [ ] one switch controls all quality checks (`off|fast|strict`)
- [ ] CI uses `strict`, local default uses `fast`
- [ ] profile state is visible in one status command

---

## Reasoning/cost controls (current concern: too high) 🧮

### Objective
Keep default reasoning on `medium` but cap drift in long autopilot loops.

- [ ] Add runtime policy knobs:
  - [ ] `autopilot.reasoning.default = medium`
  - [ ] `autopilot.reasoning.max_per_cycle = medium`
  - [ ] `autopilot.reasoning.escalation = manual_only` (or conditional)
  - [ ] `autopilot.iteration.max = <n>`
  - [ ] `autopilot.budget.wall_clock_seconds` per profile

- [ ] Add automatic downgrade rule:
  - [ ] if no blocker + repetitive cycles -> lower effort for next cycle

- [ ] Add visibility:
  - [ ] `/autopilot status --json` includes reasoning profile + changes over time

---

## Migration phases (execution checklist) 🚚

### Phase 1 — Gateway baseline (next)
- [x] Create `plugin/gateway-core` package (TS + lint + build + tests) *(scaffold complete)*
- [ ] Implement config schema + state storage
- [ ] Implement hook registry with feature flags

Recent progress:

- [x] Added gateway-core focused unit tests for command parsing and orphan cleanup state behavior.
- [x] Added command-layer hook diagnostics in `/gateway status|doctor --json`.

### Phase 2 — Autopilot hook parity
- [ ] Move loop continuation logic to hook events (`session.idle`)
- [ ] Keep `/autopilot*` Python commands as control facade
- [x] Add `/ralph-loop` and `/cancel-ralph` bridge parity *(compatibility aliases only; no separate runtime semantics)*

### Phase 3 — Safety and policy packs
- [ ] Add guard hooks (scope/budget/anti-loop/kill-switch)
- [ ] Add deterministic reason codes and doctor diagnostics

### Phase 4 — Quality controls
- [ ] Implement quality profile toggles (`off|fast|strict`)
- [ ] Wire Make + slash commands

### Phase 5 — Stabilization
- [ ] E2E matrix pass (fresh install, local config, long-loop reliability)
- [ ] Deprecate duplicated legacy script loop paths

---

## Immediate execution queue (ordered) 🗂️

1. [ ] Create `plugin/gateway-core` package scaffold and move autopilot-loop under it.
   - status: scaffold created; autopilot-loop move pending.
2. [ ] Wire runtime event hooks (`session.idle`, `session.deleted`, `session.error`) to active plugin loading path.
3. [ ] Bridge `/autopilot*` Python commands to plugin state operations (start/status/stop/doctor).
   - status: gateway bridge state is now read/write across start/go/status/report/pause/stop; plugin-core runtime migration still pending.
4. [ ] Add kill-switch + orphan cleanup in plugin state manager.
   - status: command-bridge orphan cleanup shipped; plugin-core manager parity pending.
5. [ ] Add quality profile toggles (`off|fast|strict`) with Make + slash commands.
6. [ ] Run full E2E matrix and lock migration completion criteria.

---

## E2E acceptance checklist ✅

- [ ] `/autopilot` continues across idle events without manual nudges
- [ ] Promise mode completes only after explicit completion signal
- [ ] Objective mode completes only after objective gates pass
- [x] `/cancel-ralph` always stops active loop
- [ ] Budget/scope guardrails stop safely with clear reason codes
- [ ] `doctor` output clearly shows plugin health and active mode

---

## Notes

- Keep implementation readable first, then optimize.
- Avoid large rewrites to command bridge language during gateway migration.
- Prefer incremental, reversible steps with strong validation.
- If behavior diverges from expected continuity, prefer reason-code observability over implicit retries.
