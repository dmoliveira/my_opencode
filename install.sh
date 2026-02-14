#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/dmoliveira/my_opencode.git}"
REPO_REF="${REPO_REF:-}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.config/opencode/my_opencode}"
CONFIG_DIR="$HOME/.config/opencode"
CONFIG_PATH="$CONFIG_DIR/opencode.json"
NON_INTERACTIVE=false
SKIP_SELF_CHECK=false
RUN_WIZARD=false
WIZARD_RECONFIGURE=false

while [ "$#" -gt 0 ]; do
	case "$1" in
	--non-interactive)
		NON_INTERACTIVE=true
		;;
	--skip-self-check)
		SKIP_SELF_CHECK=true
		;;
	--wizard)
		RUN_WIZARD=true
		;;
	--reconfigure)
		WIZARD_RECONFIGURE=true
		;;
	-h | --help)
		printf "Usage: %s [--non-interactive] [--skip-self-check] [--wizard] [--reconfigure]\n" "$0"
		exit 0
		;;
	*)
		printf "Error: unknown argument: %s\n" "$1" >&2
		exit 2
		;;
	esac
	shift
done

if ! command -v git >/dev/null 2>&1; then
	printf "Error: git is required but not installed.\n" >&2
	exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
	printf "Error: python3 is required but not installed.\n" >&2
	exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
	printf "Updating existing config repo at %s\n" "$INSTALL_DIR"
	git -C "$INSTALL_DIR" fetch --all --prune
	git -C "$INSTALL_DIR" pull --ff-only
else
	if [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR/.git" ]; then
		printf "Error: %s exists and is not a git repository.\n" "$INSTALL_DIR" >&2
		exit 1
	fi
	printf "Cloning config repo into %s\n" "$INSTALL_DIR"
	git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

if [ -n "$REPO_REF" ]; then
	printf "Checking out repo ref %s\n" "$REPO_REF"
	git -C "$INSTALL_DIR" fetch --all --prune >/dev/null 2>&1 || true
	git -C "$INSTALL_DIR" checkout "$REPO_REF"
fi

chmod +x "$INSTALL_DIR/scripts/mcp_command.py" "$INSTALL_DIR/scripts/plugin_command.py" "$INSTALL_DIR/scripts/notify_command.py" "$INSTALL_DIR/scripts/session_digest.py" "$INSTALL_DIR/scripts/opencode_session.sh" "$INSTALL_DIR/scripts/telemetry_command.py" "$INSTALL_DIR/scripts/post_session_command.py" "$INSTALL_DIR/scripts/policy_command.py" "$INSTALL_DIR/scripts/doctor_command.py" "$INSTALL_DIR/scripts/config_command.py" "$INSTALL_DIR/scripts/stack_profile_command.py" "$INSTALL_DIR/scripts/install_wizard.py" "$INSTALL_DIR/scripts/nvim_integration_command.py" "$INSTALL_DIR/scripts/devtools_command.py" "$INSTALL_DIR/scripts/background_task_manager.py" "$INSTALL_DIR/scripts/refactor_lite_command.py"
if [ -f "$INSTALL_DIR/scripts/session_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/session_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/browser_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/browser_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/todo_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/todo_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/resume_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/resume_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/safe_edit_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/safe_edit_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/budget_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/budget_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/autopilot_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/autopilot_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/pr_review_analyzer.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/pr_review_analyzer.py"
fi
if [ -f "$INSTALL_DIR/scripts/pr_review_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/pr_review_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/release_train_engine.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/release_train_engine.py"
fi
if [ -f "$INSTALL_DIR/scripts/release_train_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/release_train_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/hotfix_runtime.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/hotfix_runtime.py"
fi
if [ -f "$INSTALL_DIR/scripts/hotfix_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/hotfix_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/health_score_collector.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/health_score_collector.py"
fi
if [ -f "$INSTALL_DIR/scripts/health_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/health_command.py"
fi
if [ -f "$INSTALL_DIR/scripts/learn_command.py" ]; then
	chmod +x "$INSTALL_DIR/scripts/learn_command.py"
fi
ln -sfn "$INSTALL_DIR/opencode.json" "$CONFIG_PATH"

if [ -d "$INSTALL_DIR/agent" ]; then
	mkdir -p "$CONFIG_DIR/agent"
	cp -f "$INSTALL_DIR"/agent/*.md "$CONFIG_DIR/agent/" 2>/dev/null || true
fi

if [ "$RUN_WIZARD" = true ]; then
	printf "\nRunning install wizard...\n"
	WIZARD_ARGS=()
	if [ "$WIZARD_RECONFIGURE" = true ]; then
		WIZARD_ARGS+=("--reconfigure")
	fi
	if [ "$NON_INTERACTIVE" = true ]; then
		WIZARD_ARGS+=("--non-interactive")
	fi
	python3 "$INSTALL_DIR/scripts/install_wizard.py" "${WIZARD_ARGS[@]}"
fi

if [ "$SKIP_SELF_CHECK" = false ]; then
	printf "\nRunning self-check...\n"
	python3 "$INSTALL_DIR/scripts/mcp_command.py" status
	python3 "$INSTALL_DIR/scripts/plugin_command.py" status
	python3 "$INSTALL_DIR/scripts/notify_command.py" status
	python3 "$INSTALL_DIR/scripts/notify_command.py" doctor
	python3 "$INSTALL_DIR/scripts/session_digest.py" show || true
	python3 "$INSTALL_DIR/scripts/session_digest.py" doctor
	if [ -f "$INSTALL_DIR/scripts/session_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/session_command.py" list --json
		python3 "$INSTALL_DIR/scripts/session_command.py" search selfcheck --json
		python3 "$INSTALL_DIR/scripts/session_command.py" doctor --json
	fi
	python3 "$INSTALL_DIR/scripts/telemetry_command.py" status
	python3 "$INSTALL_DIR/scripts/post_session_command.py" status
	python3 "$INSTALL_DIR/scripts/policy_command.py" status
	python3 "$INSTALL_DIR/scripts/config_command.py" status
	python3 "$INSTALL_DIR/scripts/config_command.py" layers
	python3 "$INSTALL_DIR/scripts/background_task_manager.py" status
	python3 "$INSTALL_DIR/scripts/background_task_manager.py" doctor --json
	if [ -f "$INSTALL_DIR/scripts/refactor_lite_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/refactor_lite_command.py" profile --scope "scripts/*.py" --dry-run --json
	fi
	python3 "$INSTALL_DIR/scripts/stack_profile_command.py" status
	python3 "$INSTALL_DIR/scripts/browser_command.py" status
	python3 "$INSTALL_DIR/scripts/browser_command.py" doctor --json
	SELF_CHECK_PLAN="$HOME/.config/opencode/my_opencode/.install-selfcheck-plan.md"
	python3 -c "from pathlib import Path; Path('$SELF_CHECK_PLAN').write_text('---\nid: install-selfcheck-plan\ntitle: Install Selfcheck Plan\nowner: installer\ncreated_at: 2026-02-13T00:00:00Z\nversion: 1\n---\n\n# Plan\n\n- [ ] 1. Confirm command wiring\n- [ ] 2. Confirm checkpoint persistence\n', encoding='utf-8')"
	if [ -f "$INSTALL_DIR/scripts/todo_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/todo_command.py" status --json
		python3 "$INSTALL_DIR/scripts/todo_command.py" enforce --json
	fi
	if [ -f "$INSTALL_DIR/scripts/resume_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/resume_command.py" status --json || true
		RUNTIME_PATH="$HOME/.config/opencode/my_opencode/runtime/plan_execution.json"
		python3 -c "import json,pathlib; p=pathlib.Path('$RUNTIME_PATH'); data=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; steps=data.get('steps', []); data['status']='failed'; data['resume']={'enabled': True, 'attempt_count': 0, 'max_attempts': 3, 'trail': []};
if isinstance(steps, list) and len(steps) >= 2:
  steps[0]['state']='done';
  steps[1]['state']='pending';
  steps[1]['idempotent']=False;
p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')"
		python3 "$INSTALL_DIR/scripts/resume_command.py" now --interruption-class tool_failure --json || true
		if ! python3 "$INSTALL_DIR/scripts/resume_command.py" now --interruption-class tool_failure --approve-step 2 --json; then
			sleep 31
			python3 "$INSTALL_DIR/scripts/resume_command.py" now --interruption-class tool_failure --approve-step 2 --json
		fi
	fi
	if [ -f "$INSTALL_DIR/scripts/safe_edit_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/safe_edit_command.py" status --json
		python3 "$INSTALL_DIR/scripts/safe_edit_command.py" plan --operation rename --scope "scripts/*.py" --allow-text-fallback --json
		python3 "$INSTALL_DIR/scripts/safe_edit_command.py" doctor --json || true
	fi
	if [ -f "$INSTALL_DIR/scripts/checkpoint_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/checkpoint_command.py" list --json
		python3 "$INSTALL_DIR/scripts/checkpoint_command.py" show --snapshot latest --json || true
		python3 "$INSTALL_DIR/scripts/checkpoint_command.py" prune --max-per-run 50 --max-age-days 14 --json
		python3 "$INSTALL_DIR/scripts/checkpoint_command.py" doctor --json || true
	fi
	if [ -f "$INSTALL_DIR/scripts/budget_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/budget_command.py" status --json
		python3 "$INSTALL_DIR/scripts/budget_command.py" override --tool-call-count 120 --reason install-self-check --json
		python3 "$INSTALL_DIR/scripts/budget_command.py" doctor --json
		python3 "$INSTALL_DIR/scripts/budget_command.py" override --clear --json
	fi
	if [ -f "$INSTALL_DIR/scripts/autopilot_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" start --goal "Install self-check objective" --scope "scripts/autopilot_command.py" --done-criteria "verify command wiring;verify runtime status" --max-budget balanced --json
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" status --confidence 0.9 --json
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" report --json
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" pause --json
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" resume --confidence 0.9 --tool-calls 1 --token-estimate 50 --touched-paths scripts/autopilot_command.py --json
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" resume --confidence 0.9 --tool-calls 1 --token-estimate 50 --touched-paths README.md --json || true
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" stop --reason install-self-check --json
		python3 "$INSTALL_DIR/scripts/autopilot_command.py" doctor --json
	fi
	if [ -f "$INSTALL_DIR/scripts/pr_review_command.py" ]; then
		SELF_CHECK_DIFF="$HOME/.config/opencode/my_opencode/.install-selfcheck-pr.diff"
		python3 -c "from pathlib import Path; Path('$SELF_CHECK_DIFF').write_text('diff --git a/scripts/install_selfcheck.py b/scripts/install_selfcheck.py\nindex 0000000..1111111 100644\n--- a/scripts/install_selfcheck.py\n+++ b/scripts/install_selfcheck.py\n@@ -0,0 +1,1 @@\n+print(\"install\")\n', encoding='utf-8')"
		python3 "$INSTALL_DIR/scripts/pr_review_command.py" --diff-file "$SELF_CHECK_DIFF" --json
		python3 "$INSTALL_DIR/scripts/pr_review_command.py" checklist --diff-file "$SELF_CHECK_DIFF" --json
		python3 "$INSTALL_DIR/scripts/pr_review_command.py" doctor --json
	fi
	if [ -f "$INSTALL_DIR/scripts/release_train_command.py" ]; then
		python3 "$INSTALL_DIR/scripts/release_train_command.py" status --json
		python3 "$INSTALL_DIR/scripts/release_train_command.py" prepare --version 0.0.1 --json || true
		python3 "$INSTALL_DIR/scripts/release_train_command.py" draft --head HEAD --json
		python3 "$INSTALL_DIR/scripts/release_train_command.py" doctor --json
	fi
	if [ -f "$INSTALL_DIR/scripts/hotfix_command.py" ]; then
		(
			cd "$INSTALL_DIR"
			python3 "$INSTALL_DIR/scripts/hotfix_command.py" start --incident-id INSTALL-SELF-CHECK --scope config_only --impact sev3 --json
			python3 "$INSTALL_DIR/scripts/hotfix_runtime.py" checkpoint --label install-self-check --json
			python3 "$INSTALL_DIR/scripts/hotfix_runtime.py" validate --target validate --result pass --json
			python3 "$INSTALL_DIR/scripts/hotfix_command.py" status --json
			python3 "$INSTALL_DIR/scripts/hotfix_command.py" remind --json
			python3 "$INSTALL_DIR/scripts/hotfix_command.py" close --outcome resolved --followup-issue install-self-check --deferred-validation-owner installer --deferred-validation-due 2026-03-01 --json
			python3 "$INSTALL_DIR/scripts/hotfix_command.py" doctor --json
		)
	fi
	if [ -f "$INSTALL_DIR/scripts/health_command.py" ]; then
		(
			cd "$INSTALL_DIR"
			python3 "$INSTALL_DIR/scripts/health_command.py" status --force-refresh --json
			python3 "$INSTALL_DIR/scripts/health_command.py" trend --limit 5 --json
			python3 "$INSTALL_DIR/scripts/health_command.py" drift --json
			python3 "$INSTALL_DIR/scripts/health_command.py" doctor --json
		)
	fi
	if [ -f "$INSTALL_DIR/scripts/learn_command.py" ]; then
		(
			cd "$INSTALL_DIR"
			python3 "$INSTALL_DIR/scripts/learn_command.py" capture --limit 5 --json
			LEARN_ENTRY_ID=$(python3 "$INSTALL_DIR/scripts/learn_command.py" search --limit 1 --json | python3 -c 'import json,sys; payload=json.load(sys.stdin); entries=payload.get("entries", []); print(entries[0].get("entry_id", "") if entries else "")')
			if [ -n "$LEARN_ENTRY_ID" ]; then
				python3 "$INSTALL_DIR/scripts/learn_command.py" review --entry-id "$LEARN_ENTRY_ID" --summary "install-self-check review" --confidence 88 --risk high --json
				if python3 "$INSTALL_DIR/scripts/learn_command.py" publish --entry-id "$LEARN_ENTRY_ID" --approved-by installer --json; then
					printf "learn publish high-risk single approval unexpectedly passed\n" >&2
					exit 1
				fi
				python3 "$INSTALL_DIR/scripts/learn_command.py" publish --entry-id "$LEARN_ENTRY_ID" --approved-by installer-2 --json
			fi
			python3 "$INSTALL_DIR/scripts/learn_command.py" search --query release --json
			python3 "$INSTALL_DIR/scripts/learn_command.py" doctor --json
		)
	fi
	python3 "$INSTALL_DIR/scripts/nvim_integration_command.py" status
	python3 "$INSTALL_DIR/scripts/devtools_command.py" status
	python3 "$INSTALL_DIR/scripts/doctor_command.py" run || true
	if ! python3 "$INSTALL_DIR/scripts/plugin_command.py" doctor; then
		if [ "$NON_INTERACTIVE" = true ]; then
			printf "\nSelf-check failed in non-interactive mode.\n" >&2
			exit 1
		fi
		printf "\nSelf-check reported missing prerequisites; setup can continue.\n"
		python3 "$INSTALL_DIR/scripts/plugin_command.py" setup-keys
	fi
fi

printf "\nDone! ✅\n"
printf "Config linked: %s -> %s\n" "$CONFIG_PATH" "$INSTALL_DIR/opencode.json"
printf "\nOpen OpenCode and use:\n"
printf "  /mcp status\n"
printf "  /mcp help\n"
printf "  /mcp doctor\n"
printf "  /mcp enable context7\n"
printf "  /mcp disable context7\n"
printf "  /plugin status\n"
printf "  /plugin doctor\n"
printf "  /doctor run\n"
printf "  /notify status\n"
printf "  /notify profile focus\n"
printf "  /notify doctor\n"
printf "  /digest run --reason manual\n"
printf "  /digest-run-post\n"
printf "  /digest show\n"
printf "  /digest doctor\n"
printf "  /session list --json\n"
printf "  /session search selftest --json\n"
printf "  /session doctor --json\n"
printf "  /telemetry status\n"
printf "  /telemetry profile local\n"
printf "  /post-session status\n"
printf "  /policy profile strict\n"
printf "  /config status\n"
printf "  /config layers\n"
printf "  /config backup\n"
printf "  /bg status\n"
printf "  /bg doctor --json\n"
printf "  /refactor-lite profile --scope scripts/*.py --dry-run --json\n"
printf "  /hooks status\n"
printf "  /hooks enable\n"
printf "  /hooks doctor --json\n"
printf "  /model-routing status\n"
printf "  /model-profile status\n"
printf "  /routing status\n"
printf "  /routing explain --category deep --json\n"
printf "  /keyword-mode status\n"
printf "  /keyword-mode detect --prompt 'safe-apply deep-analyze investigate this refactor'\n"
printf "  /keyword-mode disable-keyword ulw\n"
printf "  /keyword-mode doctor --json\n"
printf "  /rules status\n"
printf "  /rules explain scripts/selftest.py --json\n"
printf "  /stack apply focus\n"
printf "  /browser status\n"
printf "  /browser profile agent-browser\n"
printf "  /browser doctor --json\n"
printf "  /autopilot\n"
printf "  /autopilot go --goal 'finish current objective' --json\n"
printf "  /continue-work 'finish current objective end-to-end'\n"
printf "  /autopilot status --json\n"
printf "  /autopilot report --json\n"
printf "  /budget status --json\n"
printf "  /budget profile conservative\n"
printf "  /budget override --tool-call-count 120 --reason install-self-check --json\n"
printf "  /budget-doctor-json\n"
printf "  /autopilot start --goal 'Ship objective' --scope 'scripts/**' --done-criteria 'all checks pass' --max-budget balanced --json\n"
printf "  /autopilot status --json\n"
printf "  /autopilot report --json\n"
printf "  /autopilot pause --json\n"
printf "  /autopilot resume --confidence 0.9 --tool-calls 1 --token-estimate 50 --touched-paths scripts/autopilot_command.py --json\n"
printf "  /autopilot stop --reason manual --json\n"
printf "  /autopilot doctor --json\n"
printf "  /pr-review --base main --head HEAD --json\n"
printf "  /pr-review-checklist --base main --head HEAD\n"
printf "  /pr-review-doctor\n"
printf "  /release-train status --json\n"
printf "  /release-train prepare --version 0.0.1 --json\n"
printf "  /release-train draft --head HEAD --json\n"
printf "  /release-train-doctor\n"
printf "  /hotfix start --incident-id INC-42 --scope patch --impact sev2 --json\n"
printf "  /hotfix status --json\n"
printf "  /hotfix close --outcome resolved --followup-issue bd-123 --deferred-validation-owner oncall --deferred-validation-due 2026-03-01 --json\n"
printf "  /hotfix remind --json\n"
printf "  /hotfix doctor --json\n"
printf "  /health status --force-refresh --json\n"
printf "  /health trend --limit 10 --json\n"
printf "  /health drift --json\n"
printf "  /health doctor --json\n"
printf "  /learn capture --limit 20 --json\n"
printf "  /learn review --entry-id kc-e27-t2 --summary 'reviewed guidance' --confidence 90 --risk medium --json\n"
printf "  /learn publish --entry-id kc-e27-t2 --approved-by oncall --json\n"
printf "  /learn search --query release --json\n"
printf "  /learn doctor --json\n"
printf "  /todo status --json\n"
printf "  /todo enforce --json\n"
printf "  /resume status --json\n"
printf "  /resume now --interruption-class tool_failure --json\n"
printf "  /resume disable --json\n"
printf "  /safe-edit status --json\n"
printf "  /safe-edit plan --operation rename --scope scripts/*.py --json\n"
printf "  /safe-edit doctor --json\n"
printf "  /checkpoint list --json\n"
printf "  /checkpoint show --snapshot latest --json\n"
printf "  /checkpoint prune --max-per-run 50 --max-age-days 14 --json\n"
printf "  /checkpoint doctor --json\n"
printf "  /nvim status\n"
printf "  /devtools status\n"
printf "  /devtools install all\n"
printf "  /nvim install minimal --link-init\n"
printf "  ~/.config/opencode/my_opencode/install.sh --wizard --reconfigure\n"
printf "  /doctor-json\n"
printf "  /setup-keys\n"
printf "  /plugin enable supermemory\n"
printf "  /plugin disable supermemory\n"
