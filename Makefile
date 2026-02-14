.DEFAULT_GOAL := help

.PHONY: help validate selftest doctor doctor-json devtools-status hooks-install install-test release-check release

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "%-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

validate: ## Validate scripts and JSON config
	python3 -m py_compile scripts/*.py
	python3 -m json.tool opencode.json >/dev/null

selftest: ## Run deterministic command self-tests
	python3 scripts/selftest.py

doctor: ## Run plugin diagnostics (human-readable)
	python3 scripts/doctor_command.py run

doctor-json: ## Run plugin diagnostics (JSON)
	python3 scripts/doctor_command.py run --json

devtools-status: ## Show external productivity tooling status
	python3 scripts/devtools_command.py status

hooks-install: ## Install pre-commit and lefthook git hooks
	python3 scripts/devtools_command.py hooks-install

install-test: ## Run installer smoke test in temp HOME
	@TMP_HOME="$$(mktemp -d)"; \
	HOME="$$TMP_HOME" REPO_URL="$(PWD)" REPO_REF="$$(git rev-parse --abbrev-ref HEAD)" ./install.sh --skip-self-check; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/mcp_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/plugin_command.py" profile lean; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/plugin_command.py" doctor --json; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/notify_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/notify_command.py" doctor --json; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason install-test; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" show; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" doctor --json; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/telemetry_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/telemetry_command.py" doctor --json; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/post_session_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason manual --run-post; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/policy_command.py" profile strict; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/policy_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" layers; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" layers --json; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" backup --name install-test; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/config_command.py" list; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/stack_profile_command.py" apply focus; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/stack_profile_command.py" status; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" profile agent-browser; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" doctor --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" profile playwright; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/browser_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" ]; then PLAN_FILE="$$TMP_HOME/.config/opencode/my_opencode/.install-test-plan.md"; python3 -c "from pathlib import Path; Path('$$PLAN_FILE').write_text('---\nid: install-test-plan\ntitle: Install Test Plan\nowner: install-test\ncreated_at: 2026-02-13T00:00:00Z\nversion: 1\n---\n\n# Plan\n\n- [ ] 1. Validate command availability\n- [ ] 2. Validate status persistence\n', encoding='utf-8')"; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" "$$PLAN_FILE" --deviation "install smoke" --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" "$$PLAN_FILE" --background --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" run --max-jobs 1; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" deviations --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/start_work_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/todo_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/todo_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/todo_command.py" enforce --json; fi; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/nvim_integration_command.py" install minimal --link-init; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/nvim_integration_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/devtools_command.py" status; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" doctor --json; else echo "background_task_manager.py not present in cloned ref; skipping"; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" profile --scope "scripts/*.py" --dry-run --json; else echo "refactor_lite_command.py not present in cloned ref; skipping"; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" ]; then if HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/refactor_lite_command.py" --json; then echo "refactor_lite_command.py missing-target check unexpectedly passed" && exit 1; fi; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" status; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" enable; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" disable-hook error-hints; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" run error-hints --json '{"command":"git status","exit_code":128,"stderr":"fatal: not a git repository"}'; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" enable-hook error-hints; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/hooks_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/model_routing_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/model_routing_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/model_routing_command.py" resolve --category deep --override-model openai/nonexistent --available-models openai/gpt-5-mini,openai/gpt-5.3-codex --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" doctor --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" disable-keyword ulw; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" detect --prompt "ulw deep-analyze audit this change" --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" detect --prompt "no-keyword-mode safe-apply deep-analyze" --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/keyword_mode_command.py" enable-keyword ulw; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" explain scripts/selftest.py --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" disable-id style-python; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" doctor --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/rules_command.py" enable-id style-python; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" status --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" prepare --version 0.0.1 --json || true; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" draft --head HEAD --json; HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/release_train_command.py" doctor --json; fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/hotfix_command.py" ]; then HOTFIX_REPO="$$TMP_HOME/.config/opencode/my_opencode"; (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_command.py" start --incident-id INSTALL-TEST-1 --scope rollback --impact sev2 --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_runtime.py" checkpoint --label install-test --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_runtime.py" mark-patch --summary "rollback to stable state" --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_runtime.py" validate --target validate --result pass --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_command.py" status --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_command.py" remind --json); (cd "$$HOTFIX_REPO" && if HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_command.py" close --outcome rolled_back --json; then echo "hotfix close missing followup unexpectedly passed" && exit 1; fi); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_command.py" close --outcome rolled_back --followup-issue install-test-followup --deferred-validation-owner oncall --deferred-validation-due 2026-03-01 --json); (cd "$$HOTFIX_REPO" && HOME="$$TMP_HOME" python3 "$$HOTFIX_REPO/scripts/hotfix_command.py" doctor --json); fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/health_command.py" ]; then HEALTH_REPO="$$TMP_HOME/.config/opencode/my_opencode"; (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" python3 "$$HEALTH_REPO/scripts/health_command.py" status --force-refresh --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" python3 "$$HEALTH_REPO/scripts/health_command.py" trend --limit 5 --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" python3 "$$HEALTH_REPO/scripts/health_command.py" drift --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" python3 -c "import json,pathlib; p=pathlib.Path('$$TMP_HOME/.config/opencode/opencode.json'); data=json.loads(p.read_text(encoding='utf-8')); runtime=data.get('budget_runtime', {}); runtime['profile']='extended'; data['budget_runtime']=runtime; p.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')"); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" python3 "$$HEALTH_REPO/scripts/health_command.py" drift --force-refresh --json); (cd "$$HEALTH_REPO" && HOME="$$TMP_HOME" python3 "$$HEALTH_REPO/scripts/health_command.py" doctor --json); fi; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/learn_command.py" ]; then LEARN_REPO="$$TMP_HOME/.config/opencode/my_opencode"; (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" python3 "$$LEARN_REPO/scripts/learn_command.py" capture --limit 5 --json); LEARN_ENTRY_ID=$$(cd "$$LEARN_REPO" && HOME="$$TMP_HOME" python3 "$$LEARN_REPO/scripts/learn_command.py" search --limit 1 --json | python3 -c 'import json,sys; payload=json.load(sys.stdin); entries=payload.get("entries", []); print(entries[0].get("entry_id", "") if entries else "")'); if [ -n "$$LEARN_ENTRY_ID" ]; then (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" python3 "$$LEARN_REPO/scripts/learn_command.py" review --entry-id "$$LEARN_ENTRY_ID" --summary "install-test review" --confidence 88 --risk medium --json); (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" python3 "$$LEARN_REPO/scripts/learn_command.py" publish --entry-id "$$LEARN_ENTRY_ID" --approved-by install-test --json); fi; (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" python3 "$$LEARN_REPO/scripts/learn_command.py" search --query release --json); (cd "$$LEARN_REPO" && HOME="$$TMP_HOME" python3 "$$LEARN_REPO/scripts/learn_command.py" doctor --json); fi; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/install_wizard.py" --non-interactive --skip-extras --plugin-profile lean --mcp-profile research --policy-profile balanced --notify-profile skip --telemetry-profile local --post-session-profile manual-validate; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/doctor_command.py" run --json

release-check: validate selftest ## Verify release prerequisites
	@test -n "$(VERSION)" || (echo "VERSION is required, eg: make release-check VERSION=0.1.1" && exit 2)
	@git diff --quiet && git diff --cached --quiet || (echo "working tree must be clean before release" && exit 1)
	@git ls-files --error-unmatch CHANGELOG.md >/dev/null 2>&1 || (echo "CHANGELOG.md is missing" && exit 1)
	@git diff-tree --no-commit-id --name-only -r HEAD | grep -qx "CHANGELOG.md" || (echo "latest commit must update CHANGELOG.md before release" && exit 1)
	@python3 scripts/release_train_command.py prepare --version "$(VERSION)" --json >/dev/null || (echo "release-train preflight failed" && exit 1)
	@echo "release-check: PASS"

release: release-check ## Create and publish release (VERSION=0.1.1)
	@test -n "$(VERSION)" || (echo "VERSION is required, eg: make release VERSION=0.1.1" && exit 2)
	git tag -a "v$(VERSION)" -m "v$(VERSION)"
	git push origin "v$(VERSION)"
	gh release create "v$(VERSION)" --generate-notes
