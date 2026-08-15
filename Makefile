.DEFAULT_GOAL := help

PYTHON ?= python3
PYTHON_MIN_VERSION := 3.11
OPENCODE_BIN ?= opencode
OPENCODE_RESUME_E2E_VERSION := 1.18.18

.PHONY: python-check help validate selftest doctor doctor-json sqlite-doctor sqlite-doctor-json devtools-status hooks-install build-agents build-agents-check release-index-update docs-automation-summary-update docs-automation-check pages-readiness-check release-note-validation-check release-note-quality-check plan-hygiene-check wave-linkage-check wave-handoff-summary wave-completion-update quality-fast quality-strict quality-off quality-status gateway-status gateway-enable gateway-disable gateway-doctor gateway-secret-redaction-smoke gateway-resume-redaction-e2e gateway-resume-redaction-e2e-prebuilt gateway-execution-status-live-smoke gateway-turn-watch gateway-turn-watch-webhook harness-wave2-task4-smoke notify-icons-generate notify-icons-select reservation-status task-lease-status install-test install-test-full release-check release

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "%-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

PYTHON_TARGETS := validate build-agents build-agents-check release-index-update docs-automation-summary-update docs-automation-check pages-readiness-check release-note-validation-check release-note-quality-check plan-hygiene-check wave-linkage-check wave-handoff-summary wave-completion-update quality-fast quality-strict quality-off quality-status gateway-status gateway-enable gateway-disable gateway-doctor gateway-secret-redaction-smoke gateway-resume-redaction-e2e gateway-resume-redaction-e2e-prebuilt gateway-execution-status-live-smoke gateway-turn-watch gateway-turn-watch-webhook harness-wave2-task4-smoke notify-icons-generate notify-icons-select reservation-status task-lease-status selftest doctor doctor-json sqlite-doctor sqlite-doctor-json devtools-status hooks-install install-test install-test-full release-check release

$(PYTHON_TARGETS): python-check

python-check: ## Verify Python $(PYTHON_MIN_VERSION)+ runtime
	@$(PYTHON) -c 'import sys; required=(3, 11); current=sys.version_info[:2]; version=sys.version.split()[0]; print(f"python: {sys.executable} {version}"); sys.stderr.write(f"Error: Python {required[0]}.{required[1]}+ is required; selected {sys.executable} {version}. Fix PATH or run make PYTHON=/path/to/python3.11+ <target>.\n" if current < required else ""); raise SystemExit(2 if current < required else 0)'

validate: ## Validate scripts and JSON config
	$(PYTHON) -m py_compile scripts/*.py
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
	$(PYTHON) -m json.tool opencode.json >/dev/null
	$(PYTHON) -m json.tool tui.json >/dev/null
	$(PYTHON) scripts/hygiene_drift_check.py
	$(PYTHON) scripts/command_doc_check.py
	$(PYTHON) scripts/readme_layout_check.py
	$(PYTHON) scripts/active_doc_script_ref_check.py
	$(PYTHON) scripts/script_reachability_check.py
	$(PYTHON) scripts/layered_config_hygiene_check.py
	$(PYTHON) scripts/check_config_writer_inventory.py
	$(PYTHON) scripts/docs_automation_sync_check.py
	$(PYTHON) scripts/release_note_validation_check.py
	$(PYTHON) scripts/plan_hygiene_check.py --json
	$(PYTHON) scripts/wave_linkage_check.py --json
	$(PYTHON) scripts/build_agents.py --profile balanced --check

build-agents: ## Generate agent markdown from JSON specs
	$(PYTHON) scripts/build_agents.py --profile balanced

build-agents-check: ## Verify generated agents are up-to-date
	$(PYTHON) scripts/build_agents.py --profile balanced --check

release-index-update: ## Regenerate v0.4 release index doc
	$(PYTHON) scripts/update_release_index.py

docs-automation-summary-update: ## Regenerate docs automation summary artifact
	$(PYTHON) scripts/update_docs_automation_summary.py

docs-automation-check: ## Check docs automation workflow/pages/summary synchronization
	$(PYTHON) scripts/docs_automation_sync_check.py

pages-readiness-check: ## Check remote GitHub Pages readiness for docs automation
	$(PYTHON) scripts/pages_readiness_check.py --json

release-note-validation-check: ## Check release-note docs include validation evidence headings
	$(PYTHON) scripts/release_note_validation_check.py

release-note-quality-check: ## Score release-note quality signals for operator triage
	$(PYTHON) scripts/release_note_quality_check.py --json

plan-hygiene-check: ## Check stale done worklog rows for closure evidence links
	$(PYTHON) scripts/plan_hygiene_check.py --json

wave-linkage-check: ## Check completed wave plans map to completion docs
	$(PYTHON) scripts/wave_linkage_check.py --json

wave-handoff-summary: ## Summarize current wave transition handoff state
	$(PYTHON) scripts/wave_handoff_summary.py --json

wave-completion-update: ## Generate wave completion doc (WAVE=vX.Y, PRS="123 124")
	@if [ -z "$(WAVE)" ]; then echo "WAVE is required (for example WAVE=v2.2)"; exit 2; fi
	@ARGS=""; for pr in $(PRS); do ARGS="$$ARGS --pr $$pr"; done; $(PYTHON) scripts/update_wave_completion_doc.py --wave "$(WAVE)" $$ARGS --json

quality-fast: ## Set quality profile to fast
	$(PYTHON) scripts/quality_command.py profile fast --json

quality-strict: ## Set quality profile to strict
	$(PYTHON) scripts/quality_command.py profile strict --json

quality-off: ## Set quality profile to off
	$(PYTHON) scripts/quality_command.py profile off --json

quality-status: ## Show active quality profile
	$(PYTHON) scripts/quality_command.py status --json

gateway-status: ## Show gateway plugin status
	$(PYTHON) scripts/gateway_command.py status --json

gateway-enable: ## Enable gateway plugin file entry
	$(PYTHON) scripts/gateway_command.py enable --json

gateway-disable: ## Disable gateway plugin file entry
	$(PYTHON) scripts/gateway_command.py disable --json

gateway-doctor: ## Run gateway plugin diagnostics
	$(PYTHON) scripts/gateway_command.py doctor --json

gateway-secret-redaction-smoke: ## Verify provider-boundary redaction against localhost
	$(PYTHON) scripts/gateway_secret_redaction_live_smoke.py --repo-root "$(CURDIR)" --json

gateway-resume-redaction-e2e: ## Build and gate large-session resume redaction on OpenCode $(OPENCODE_RESUME_E2E_VERSION)
	npm --prefix plugin/gateway-core run build
	$(MAKE) --no-print-directory gateway-resume-redaction-e2e-prebuilt OPENCODE_BIN="$(OPENCODE_BIN)"

gateway-resume-redaction-e2e-prebuilt: ## Gate resume redaction using the existing gateway build
	$(PYTHON) scripts/gateway_resume_redaction_e2e.py --repo-root "$(CURDIR)" --opencode-bin "$(OPENCODE_BIN)" --json

gateway-execution-status-live-smoke: ## Verify gateway execution status through a real local OpenCode server
	npm --prefix plugin/gateway-core run build
	$(PYTHON) scripts/gateway_execution_status_live_smoke.py --opencode-bin "$(OPENCODE_BIN)" --without-bun --output json

gateway-turn-watch: ## Stream long-turn alerts from gateway audit
	$(PYTHON) scripts/gateway_turn_watch.py --follow --json

gateway-turn-watch-webhook: ## Stream long-turn alerts and POST to WEBHOOK_URL
	@if [ -z "$(WEBHOOK_URL)" ]; then echo "WEBHOOK_URL is required"; exit 2; fi
	$(PYTHON) scripts/gateway_turn_watch.py --follow --json --webhook-url "$(WEBHOOK_URL)"

harness-wave2-task4-smoke: ## Run pinned MCP and exact-model wave-2 smokes
	$(PYTHON) scripts/harness_wave2_task4_smoke.py all --repo-root "$(CURDIR)" --model openai/gpt-5.4-mini --json

notify-icons-generate: ## Generate versioned notification icon candidates (OpenAI)
	$(PYTHON) scripts/notify_icon_generate.py --version "$${NOTIFY_ICON_VERSION:-v1}"

notify-icons-select: ## Select candidate for event (EVENT, CANDIDATE, VERSION)
	@if [ -z "$(EVENT)" ] || [ -z "$(CANDIDATE)" ]; then echo "EVENT and CANDIDATE are required"; exit 2; fi
	$(PYTHON) scripts/notify_icon_select.py --version "$${NOTIFY_ICON_VERSION:-v1}" --event "$(EVENT)" --candidate-index "$(CANDIDATE)"

reservation-status: ## Show file reservation state used by parallel writer guards
	$(PYTHON) scripts/reservation_command.py status --json

task-lease-status: ## Show cooperative Codememory task lease state
	$(PYTHON) scripts/task_lease_command.py status --json

selftest: ## Run deterministic command self-tests
	$(PYTHON) scripts/selftest.py

doctor: ## Run plugin diagnostics (human-readable)
	$(PYTHON) scripts/doctor_command.py run

doctor-json: ## Run plugin diagnostics (JSON)
	$(PYTHON) scripts/doctor_command.py run --json

sqlite-doctor: ## Inspect all local SQLite stores (human-readable)
	$(PYTHON) scripts/sqlite_doctor_command.py run

sqlite-doctor-json: ## Inspect all local SQLite stores (JSON)
	$(PYTHON) scripts/sqlite_doctor_command.py run --json

devtools-status: ## Show external productivity tooling status
	$(PYTHON) scripts/devtools_command.py status

hooks-install: ## Install pre-commit git hooks
	$(PYTHON) scripts/devtools_command.py hooks-install

install-test install-test-full: SHELL := /bin/bash

install-test: ## Run installer smoke test in temp HOME
	@set -euo pipefail; \
	TMP_HOME="$$(mktemp -d)"; \
	trap 'rm -rf "$$TMP_HOME"' EXIT HUP INT TERM; \
	SOURCE_REPO="$(PWD)"; \
	SOURCE_REF="$$(git rev-parse --abbrev-ref HEAD)"; \
	mkdir -p "$$TMP_HOME/.config/opencode"; \
	printf '%s\n' '{"theme":"preserved","plugin":[["npm:existing-plugin",{}]]}' > "$$TMP_HOME/.config/opencode/tui.json"; \
	HOME="$$TMP_HOME" REPO_URL="$$SOURCE_REPO" REPO_REF="$$SOURCE_REF" ./install.sh --self-check-profile core; \
	cd "$$TMP_HOME/.config/opencode/my_opencode"; \
	HOME="$$TMP_HOME" $(PYTHON) -c 'import json; from pathlib import Path; root = Path.home() / ".config" / "opencode"; tui = json.loads((root / "tui.json").read_text()); config = json.loads((root / "opencode.json").read_text()); assert tui["theme"] == "preserved"; assert ["npm:existing-plugin", {}] in tui["plugin"]; assert any(isinstance(item, list) and item[0].endswith("/plugin/gateway-sidebar") for item in tui["plugin"]); assert config["plugin"] == ["file://{env:HOME}/.config/opencode/my_opencode/plugin/gateway-core/dist/index.js"]'; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/mcp_command.py" status; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/plugin_command.py" profile lean; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/plugin_command.py" doctor --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/notify_command.py" status; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/notify_command.py" doctor --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason install-test; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" show; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" doctor --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_command.py" doctor --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_command.py" repair-sidecars --json; \
	HOME="$$TMP_HOME" $(PYTHON) -c 'from pathlib import Path; root = Path.home() / ".config" / "opencode"; digest = root / "digests" / "last-session.json"; index = root / "sessions" / "index.json"; paths = [digest, index, digest.with_name(digest.name + ".lock"), index.with_name(index.name + ".lock")]; assert all((path.stat().st_mode & 0o777) == 0o600 for path in paths); assert (digest.parent.stat().st_mode & 0o777) == 0o700; assert (index.parent.stat().st_mode & 0o777) == 0o700'; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/telemetry_command.py" status; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/telemetry_command.py" doctor --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/post_session_command.py" status; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason manual --run-post; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/policy_command.py" profile strict; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/policy_command.py" status; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/quality_command.py" profile fast --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/quality_command.py" status --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/quality_command.py" doctor --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/gateway_command.py" status --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/gateway_command.py" doctor --json; \
	if [ "$${MY_OPENCODE_RUN_LIVE_RELAUNCH_SMOKE:-0}" = "1" ]; then HOME="$$TMP_HOME" XDG_CACHE_HOME="$$TMP_HOME/.cache" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/gateway_live_relaunch_smoke.py" --home "$$TMP_HOME" --repo-root "$$TMP_HOME/.config/opencode/my_opencode" --sync-source-dist "$$SOURCE_REPO/plugin/gateway-core/dist" --output-dir "$$TMP_HOME/.config/opencode/my_opencode/runtime/live-relaunch-smoke" --json; else echo "gateway live relaunch smoke: SKIP (set MY_OPENCODE_RUN_LIVE_RELAUNCH_SMOKE=1 for model-backed integration)"; fi; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" layers; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" layers --json; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" backup --name install-test; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" list; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/stack_profile_command.py" apply focus; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/stack_profile_command.py" status; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" profile agent-browser; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" doctor --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" profile playwright; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/tmux_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/tmux_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/tmux_command.py" config enabled true; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/tmux_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/my_opencode_cli.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/my_opencode_cli.py" version; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/my_opencode_cli.py" doctor --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/my_opencode_cli.py" install --repo-url "$$SOURCE_REPO" --repo-ref "$$SOURCE_REF" --install-dir "$$TMP_HOME/.config/opencode/my_opencode-cli-test" --dry-run; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" ]; then PLAN_FILE="$$TMP_HOME/.config/opencode/my_opencode/.install-test-plan.md"; $(PYTHON) -c "from pathlib import Path; Path('$$PLAN_FILE').write_text('---\nid: install-test-plan\ntitle: Install Test Plan\nowner: install-test\ncreated_at: 2026-02-13T00:00:00Z\nversion: 1\n---\n\n# Plan\n\n- [ ] 1. Validate command availability\n- [ ] 2. Validate status persistence\n', encoding='utf-8')"; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" "$$PLAN_FILE" --deviation "install smoke" --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" "$$PLAN_FILE" --background --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" run --max-jobs 1; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" deviations --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/todo_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/todo_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/todo_command.py" enforce --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/task_graph_command.py" ]; then TASK_ID=$$(HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/task_graph_command.py" create --subject "install test task" --owner install-test --json | $(PYTHON) -c 'import json,sys; print((json.load(sys.stdin).get("task") or {}).get("id") or "")'); HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/task_graph_command.py" list --json; if [ -n "$$TASK_ID" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/task_graph_command.py" update "$$TASK_ID" --status completed --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/task_graph_command.py" ready --json; fi; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/task_graph_command.py" doctor --json; fi; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/nvim_integration_command.py" install minimal --link-init; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/nvim_integration_command.py" status; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/devtools_command.py" status; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" doctor --json; else echo "background_task_manager.py not present in cloned ref; skipping"; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" profile --scope "scripts/*.py" --dry-run --json; else echo "refactor_lite_command.py not present in cloned ref; skipping"; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" ]; then if HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" --json; then echo "refactor_lite_command.py missing-target check unexpectedly passed" && exit 1; fi; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" status; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" enable; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" disable-hook error-hints; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" run error-hints --json '{"command":"git status","exit_code":128,"stderr":"fatal: not a git repository"}'; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" enable-hook error-hints; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/model_routing_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/model_routing_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/model_routing_command.py" resolve --category deep --override-model openai/nonexistent --available-models openai/gpt-5.1-codex-mini,openai/gpt-5.4 --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" doctor --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" disable-keyword ulw; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" detect --prompt "ulw deep-analyze audit this change" --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" detect --prompt "no-keyword-mode safe-apply deep-analyze" --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" enable-keyword ulw; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" explain scripts/selftest.py --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" disable-id style-python; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" doctor --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" enable-id style-python; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" ]; then HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" status --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" prepare --version 0.0.1 --json || true; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" draft --head HEAD --json; HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/hotfix_command.py" ]; then HOTFIX_SOURCE="$$TMP_HOME/.config/opencode/my_opencode"; HOTFIX_REPO="$$TMP_HOME/.install-test-hotfix-worktree"; git -C "$$HOTFIX_SOURCE" worktree add --detach "$$HOTFIX_REPO" HEAD >/dev/null; (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_command.py" start --incident-id INSTALL-TEST-1 --scope rollback --impact sev2 --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_runtime.py" checkpoint --label install-test --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_runtime.py" mark-patch --summary "rollback to stable state" --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_runtime.py" validate --target validate --result pass --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_command.py" status --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_command.py" remind --json); (cd "$$HOTFIX_REPO" && if HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_command.py" close --outcome rolled_back --json; then echo "hotfix close missing followup unexpectedly passed" && exit 1; fi); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_command.py" close --outcome rolled_back --followup-issue install-test-followup --deferred-validation-owner oncall --deferred-validation-due 2026-03-01 --postmortem-id install-test-postmortem --risk-ack "disposable install test risk acknowledged" --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HOTFIX_REPO/scripts/hotfix_command.py" doctor --json); git -C "$$HOTFIX_SOURCE" worktree remove --force "$$HOTFIX_REPO" >/dev/null; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/health_command.py" ]; then HEALTH_REPO="$$TMP_HOME/.config/opencode/my_opencode"; (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HEALTH_REPO/scripts/health_command.py" status --force-refresh --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HEALTH_REPO/scripts/health_command.py" trend --limit 5 --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HEALTH_REPO/scripts/health_command.py" drift --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" $(PYTHON) -c "import json,pathlib; p=pathlib.Path('$$TMP_HOME/.config/opencode/opencode.json'); data=json.loads(p.read_text(encoding='utf-8')); runtime=data.get('budget_runtime', {}); runtime['profile']='extended'; data['budget_runtime']=runtime; p.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')"); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HEALTH_REPO/scripts/health_command.py" drift --force-refresh --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$HEALTH_REPO/scripts/health_command.py" doctor --json); fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/learn_command.py" ]; then LEARN_REPO="$$TMP_HOME/.config/opencode/my_opencode"; (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$LEARN_REPO/scripts/learn_command.py" capture --limit 5 --json); LEARN_ENTRIES_PATH="$$TMP_HOME/.config/opencode/my_opencode/runtime/knowledge_entries.json"; LEARN_ENTRIES_PATH="$$LEARN_ENTRIES_PATH" $(PYTHON) -c 'import json,os,pathlib; p=pathlib.Path(os.environ["LEARN_ENTRIES_PATH"]); entries=json.loads(p.read_text(encoding="utf-8")) if p.exists() else []; sources=list(entries[0].get("evidence_sources", [])) if entries else []; sources.append("install-test:second-source") if entries and "install-test:second-source" not in sources else None; entries[0]["evidence_sources"]=sources if entries else []; p.write_text(json.dumps(entries, indent=2)+"\n", encoding="utf-8") if entries else None'; LEARN_ENTRY_ID=$$(cd "$$LEARN_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$LEARN_REPO/scripts/learn_command.py" search --limit 1 --json | $(PYTHON) -c 'import json,sys; payload=json.load(sys.stdin); entries=payload.get("entries", []); print(entries[0].get("entry_id", "") if entries else "")'); if [ -n "$$LEARN_ENTRY_ID" ]; then (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$LEARN_REPO/scripts/learn_command.py" review --entry-id "$$LEARN_ENTRY_ID" --summary "install-test review" --confidence 88 --risk high --json); (cd "$$LEARN_REPO" && if HOME="$$TMP_HOME" $(PYTHON) "$$LEARN_REPO/scripts/learn_command.py" publish --entry-id "$$LEARN_ENTRY_ID" --approved-by install-test --json; then echo "learn publish high-risk single approval unexpectedly passed" && exit 1; fi); (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$LEARN_REPO/scripts/learn_command.py" publish --entry-id "$$LEARN_ENTRY_ID" --approved-by install-test-2 --json); fi; (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$LEARN_REPO/scripts/learn_command.py" search --query release --json); (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" $(PYTHON) "$$LEARN_REPO/scripts/learn_command.py" doctor --json); fi; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/install_wizard.py" --non-interactive --skip-extras --plugin-profile lean --mcp-profile research --policy-profile balanced --notify-profile skip --telemetry-profile local --post-session-profile manual-validate; \
	HOME="$$TMP_HOME" $(PYTHON) "$$TMP_HOME/.config/opencode/my_opencode/scripts/doctor_command.py" run --json

install-test-full: ## Run the full installer self-check in disposable HOME
	@set -eu; \
	TMP_HOME="$$(mktemp -d)"; \
	trap 'rm -rf "$$TMP_HOME"' EXIT HUP INT TERM; \
	SOURCE_REPO="$(PWD)"; \
	SOURCE_SNAPSHOT="$$TMP_HOME/install-source"; \
	git clone --no-hardlinks "$$SOURCE_REPO" "$$SOURCE_SNAPSHOT" >/dev/null; \
	git diff --binary HEAD > "$$TMP_HOME/install-source.patch"; \
	if [ -s "$$TMP_HOME/install-source.patch" ]; then git -C "$$SOURCE_SNAPSHOT" apply --binary "$$TMP_HOME/install-source.patch"; fi; \
	while IFS= read -r -d '' path; do mkdir -p "$$SOURCE_SNAPSHOT/$$(dirname "$$path")"; cp -pPR "$$path" "$$SOURCE_SNAPSHOT/$$path"; done < <(git ls-files --others --exclude-standard -z); \
	git -C "$$SOURCE_SNAPSHOT" add -A; \
	if ! git -C "$$SOURCE_SNAPSHOT" diff --cached --quiet; then git -C "$$SOURCE_SNAPSHOT" -c user.name=install-test -c user.email=install-test@example.invalid commit -qm install-test-snapshot; fi; \
	SOURCE_REF="$$(git -C "$$SOURCE_SNAPSHOT" rev-parse HEAD)"; \
	HOME="$$TMP_HOME" REPO_URL="$$SOURCE_SNAPSHOT" REPO_REF="$$SOURCE_REF" ./install.sh --non-interactive --self-check-profile full; \
	if [ -f "$$SOURCE_REPO/scripts/.install-test-ci-untracked.py" ]; then test -f "$$SOURCE_SNAPSHOT/scripts/.install-test-ci-untracked.py"; test -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/.install-test-ci-untracked.py"; fi

release-check: validate selftest gateway-resume-redaction-e2e ## Verify release prerequisites
	@test -n "$(VERSION)" || (echo "VERSION is required, eg: make release-check VERSION=0.1.1" && exit 2)
	@git diff --quiet && git diff --cached --quiet || (echo "working tree must be clean before release" && exit 1)
	@git ls-files --error-unmatch CHANGELOG.md >/dev/null 2>&1 || (echo "CHANGELOG.md is missing" && exit 1)
	@git diff-tree --no-commit-id --name-only -r HEAD | grep -qx "CHANGELOG.md" || (echo "latest commit must update CHANGELOG.md before release" && exit 1)
	@$(PYTHON) scripts/release_train_command.py prepare --version "$(VERSION)" --json >/dev/null || (echo "release-train preflight failed" && exit 1)
	@echo "release-check: PASS"

release: release-check ## Create and publish release (VERSION=0.1.1)
	@test -n "$(VERSION)" || (echo "VERSION is required, eg: make release VERSION=0.1.1" && exit 2)
	$(PYTHON) scripts/release_train_command.py publish --version "$(VERSION)" --profile runtime --confirm
