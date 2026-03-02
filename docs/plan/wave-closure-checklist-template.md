# Wave Closure Checklist Template

Use this checklist before closing a minor flow wave and opening the next one.

## Closure Gates

- [ ] All epic checklist items in `docs/plan/vX.Y-flow-wave-plan.md` are marked done.
- [ ] `docs/plan/vX.Y-flow-wave-completion.md` exists and includes merged PR evidence rows.
- [ ] Completion doc references `docs/plan/vX.Y-flow-wave-plan.md` in closure criteria.
- [ ] Validation evidence is recorded:
  - `make validate`
  - `make selftest`
  - `make install-test`
  - `npm --prefix plugin/gateway-core run lint`
  - `pre-commit run --all-files`

## Transition Steps

- [ ] Open `docs/plan/vX.(Y+1)-flow-wave-plan.md` with scoped epics and validation gates.
- [ ] Link next-wave scaffold in closure notes and operator runbook updates.
- [ ] Confirm `python3 scripts/wave_linkage_check.py --json` reports PASS.
