# Feature Review and Gap Notes

Date: 2026-02-14

## What we validated

- Ran `make validate`, `make selftest`, and `make install-test` from this repo.
- Ran an additional isolated install in a random temp HOME and executed representative commands (`doctor`, `auto-slash`, `rules`, `resume`, `autopilot`, `browser`, `stack`).
- Compared current local config (`~/.config/opencode/opencode.json`) against repo config (`opencode.json`).
- Compared current scope against `oh-my-opencode` docs (`docs/features.md`, `docs/configurations.md`, `docs/orchestration-guide.md`).

## Confirmed working (in clean temp install)

- Core command stack executes end-to-end in isolated install smoke tests.
- Major custom subsystems work in isolation: `/mcp`, `/plugin`, `/notify`, `/digest`, `/config`, `/bg`, `/hooks`, `/model-routing`, `/routing`, `/keyword-mode`, `/rules`, `/resilience`, `/stack`, `/browser`, `/start-work`, `/nvim`, `/devtools`.
- Extended subsystems also execute in installer smoke path: `/budget`, `/autoflow`, `/autopilot`, `/pr-review`, `/release-train`, `/hotfix`, `/health`, `/learn`, `/todo`, `/resume`, `/safe-edit`, `/checkpoint`.

## High-priority issues to fix

1. Local install path is broken

- Your active config points command templates to `~/.config/opencode/my_opencode/scripts/...`.
- That directory does not exist locally, so command execution fails when run from real config.
- Example failure: `python3 ~/.config/opencode/my_opencode/scripts/doctor_command.py run --json` -> file not found.

2. Local config is behind repo config

- Repo has 194 command entries; local config has 123 (71 missing).
- Missing families include: `auto-slash`, `autoflow`, `autopilot`, `budget`, `checkpoint`, `health`, `hotfix`, `learn`, `pr-review`, `release-train`, `resume`, `safe-edit`, `session`, `todo`.

3. Auto-slash precision metric bug

- `/auto-slash doctor --json` can report impossible precision values (example: `1.25`).
- Root cause: `correct` counts true negatives while denominator uses only predicted positives.
- File: `scripts/auto_slash_schema.py` (`evaluate_precision`).

4. New-session UX returns hard FAIL for expected empty state

- `/autopilot status --json` returns `FAIL` with `autopilot_runtime_missing` before any run.
- `/resume status --json` returns `FAIL` with `resume_missing_checkpoint` before any run.
- This is technically consistent but noisy for first-use diagnostics.

5. Plugin doctor fails by default in fresh env

- `/doctor run --json` fails when `wakatime` is enabled but `~/.wakatime.cfg` key is absent.
- Consider defaulting to warning or auto-switching to a non-failing baseline profile on first install.

6. Installer self-check can stop early in resume path

- During local real-HOME install, `install.sh` self-check reached `/resume now` twice in sequence.
- Second call can hit cooldown (`resume_blocked_cooldown`) and return non-zero, which stops the installer due `set -e`.
- This leaves setup partially validated even though core files are already installed.

## Parity gaps vs oh-my-opencode (not currently implemented here)

If you want closer behavior to `oh-my-opencode`, these are still missing:

- Multi-agent orchestration stack (Sisyphus/Prometheus/Atlas/Hephaestus-style workflow).
- `@plan` style planning handoff and boulder-style continuity model.
- Loop-oriented commands (`/ralph-loop`, `/ulw-loop`, `/init-deep`) and related hook semantics.
- Richer built-in hook catalog (many quality/recovery/context hooks in upstream project).
- Built-in MCP parity (notably websearch/Exa path from upstream docs).
- Tmux visual multi-agent execution mode.

## Recommended fix order

1. Repair local installation linkage (`~/.config/opencode/my_opencode` path) and re-apply config from this repo.
2. Sync local `opencode.json` with repo `opencode.json` so missing command families become available.
3. Fix `auto_slash_schema.evaluate_precision` metric calculation.
4. Downgrade first-run `autopilot/resume` empty-state failures to non-fatal status or warn-level.
5. Adjust plugin doctor defaults (or install profile) to avoid hard fail when optional secrets are missing.
6. Make install self-check resume sequence cooldown-safe (sleep/retry or tolerate expected cooldown fail).
