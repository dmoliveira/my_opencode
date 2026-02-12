.DEFAULT_GOAL := help

.PHONY: help validate selftest doctor doctor-json install-test release

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "%-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

validate: ## Validate scripts and JSON config
	python3 -m py_compile scripts/*.py
	python3 -m json.tool opencode.json >/dev/null

selftest: ## Run deterministic command self-tests
	python3 scripts/selftest.py

doctor: ## Run plugin diagnostics (human-readable)
	python3 scripts/plugin_command.py doctor

doctor-json: ## Run plugin diagnostics (JSON)
	python3 scripts/plugin_command.py doctor --json

install-test: ## Run installer smoke test in temp HOME
	@TMP_HOME="$$(mktemp -d)"; \
	HOME="$$TMP_HOME" REPO_URL="$(PWD)" REPO_REF="$$(git rev-parse --abbrev-ref HEAD)" ./install.sh --skip-self-check; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/mcp_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/plugin_command.py" profile lean; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/plugin_command.py" doctor --json; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/notify_command.py" status; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" run --reason install-test; \
	HOME="$$TMP_HOME" python3 "$$TMP_HOME/.config/opencode/my_opencode/scripts/session_digest.py" show

release: ## Create and publish release (VERSION=0.1.1)
	@test -n "$(VERSION)" || (echo "VERSION is required, eg: make release VERSION=0.1.1" && exit 2)
	git tag -a "v$(VERSION)" -m "v$(VERSION)"
	git push origin "v$(VERSION)"
	gh release create "v$(VERSION)" --generate-notes
