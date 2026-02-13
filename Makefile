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
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/nvim_integration_command.py" install minimal --link-init; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/nvim_integration_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/devtools_command.py" status; \
	if [ -f "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" ]; then HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/background_task_manager.py" list --json; else echo "background_task_manager.py not present in cloned ref; skipping"; fi; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/install_wizard.py" --non-interactive --skip-extras --plugin-profile lean --mcp-profile research --policy-profile balanced --notify-profile skip --telemetry-profile local --post-session-profile manual-validate; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/doctor_command.py" run --json

release-check: validate selftest ## Verify release prerequisites
	@git diff --quiet && git diff --cached --quiet || (echo "working tree must be clean before release" && exit 1)
	@git ls-files --error-unmatch CHANGELOG.md >/dev/null 2>&1 || (echo "CHANGELOG.md is missing" && exit 1)
	@git diff-tree --no-commit-id --name-only -r HEAD | grep -qx "CHANGELOG.md" || (echo "latest commit must update CHANGELOG.md before release" && exit 1)
	@echo "release-check: PASS"

release: release-check ## Create and publish release (VERSION=0.1.1)
	@test -n "$(VERSION)" || (echo "VERSION is required, eg: make release VERSION=0.1.1" && exit 2)
	git tag -a "v$(VERSION)" -m "v$(VERSION)"
	git push origin "v$(VERSION)"
	gh release create "v$(VERSION)" --generate-notes
