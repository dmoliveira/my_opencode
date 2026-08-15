#!/usr/bin/env python3

from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
GLOBAL_SINK_MANIFEST = SCRIPTS_DIR / "config_writer_sink_manifest.json"
GLOBAL_SINK_CLASSIFICATIONS = {
    "transaction_engine",
    "checked_config_writer_exemption",
    "runtime_or_artifact_exemption",
    "isolated_fixture_exemption",
    "serialized_provisioner",
    "shell_non_config_exemption",
    "supply_chain_installer",
}
HELPER_SINK_APIS = {
    "append_exempt_text_line",
    "provision_config_json",
    "provision_config_move",
    "provision_config_symlink",
    "save_config",
}

TRANSACTIONAL_WRITERS = {
    "auto_slash_command.py",
    "browser_command.py",
    "budget_command.py",
    "config_command.py",
    "gateway_command.py",
    "hooks_command.py",
    "keyword_mode_command.py",
    "kvforge_discovery.py",
    "mcp_command.py",
    "model_routing_command.py",
    "notify_command.py",
    "plan_execution_runtime.py",
    "plugin_command.py",
    "policy_command.py",
    "post_session_command.py",
    "quality_command.py",
    "rules_command.py",
    "stack_profile_command.py",
    "telemetry_command.py",
    "tmux_command.py",
    "tui_config.py",
}
TRANSACTION_APIS = {"edit_layered_config", "edit_config_batch"}

# Function and normalized first argument form a stable callsite identity without
# relying on line numbers. Both additions and stale entries fail validation.
EXPECTED_TRANSACTION_CALLS = Counter(
    {
        ("auto_slash_command.py", "edit_state", "edit_layered_config", "mutate"): 1,
        ("browser_command.py", "edit_state", "edit_layered_config", "mutate"): 1,
        ("budget_command.py", "command_profile", "edit_layered_config", "mutate"): 1,
        ("budget_command.py", "command_override", "edit_layered_config", "mutate"): 1,
        ("config_command.py", "command_sanitize", "edit_config_batch", "tuple(participants)"): 1,
        ("config_command.py", "command_restore", "edit_config_batch", "tuple(participants)"): 1,
        ("gateway_command.py", "save_gateway_sidecar_only", "edit_layered_config", "lambda _config: None"): 1,
        ("gateway_command.py", "command_watchdog_update", "edit_layered_config", "lambda _config: None"): 1,
        ("gateway_command.py", "command_enable", "edit_layered_config", "mutate"): 1,
        ("gateway_command.py", "command_disable", "edit_layered_config", "mutate"): 1,
        ("gateway_command.py", "command_tune_memory", "edit_layered_config", "mutate"): 1,
        ("hooks_command.py", "edit_hook_settings", "edit_layered_config", "mutate"): 1,
        ("keyword_mode_command.py", "edit_state", "edit_layered_config", "mutate"): 1,
        ("kvforge_discovery.py", "write_gateway_connection", "edit_layered_config", "mutate_native"): 1,
        ("mcp_command.py", "edit_config", "edit_layered_config", "mutator"): 1,
        ("model_routing_command.py", "_write_json_atomic", "edit_layered_config", "lambda _config: None"): 1,
        ("model_routing_command.py", "edit_state", "edit_layered_config", "inspect_layered"): 1,
        ("notify_command.py", "edit_state", "edit_layered_config", "lambda _data: None"): 1,
        ("notify_command.py", "edit_state", "edit_layered_config", "mutate_layered"): 1,
        ("plan_execution_runtime.py", "save_plan_execution_state", "edit_layered_config", "mutate_layered"): 1,
        ("plugin_command.py", "edit_config", "edit_layered_config", "mutator"): 1,
        ("policy_command.py", "apply_profile", "edit_layered_config", "mutate_layered"): 1,
        ("post_session_command.py", "edit_config", "edit_layered_config", "lambda _data: None"): 1,
        ("post_session_command.py", "edit_config", "edit_layered_config", "mutate_layered"): 1,
        ("quality_command.py", "command_profile", "edit_layered_config", "lambda config: config.update({'quality': PROFILES[profile]})"): 1,
        ("rules_command.py", "edit_state", "edit_layered_config", "mutate"): 1,
        ("stack_profile_command.py", "apply_state", "edit_layered_config", "mutate_layered"): 1,
        ("telemetry_command.py", "edit_state", "edit_layered_config", "lambda _config: None"): 1,
        ("telemetry_command.py", "edit_state", "edit_layered_config", "mutate_layered"): 1,
        ("tmux_command.py", "edit_state", "edit_layered_config", "mutate"): 1,
        ("tui_config.py", "ensure_execution_sidebar", "edit_config_batch", "(ConfigFileParticipant(config_path.expanduser(), mutate),)"): 1,
    }
)

EXPECTED_PARTICIPANTS = Counter(
    {
        ("config_command.py", "command_sanitize", "file_path"): 1,
        ("config_command.py", "command_restore", "dst"): 1,
        ("gateway_command.py", "save_gateway_sidecar_only", "path"): 1,
        ("gateway_command.py", "command_watchdog_update", "sidecar_path"): 1,
        ("kvforge_discovery.py", "write_gateway_connection", "gateway_write_path"): 1,
        ("model_routing_command.py", "_write_json_atomic", "path"): 1,
        ("model_routing_command.py", "edit_state", "CONFIG_PATH"): 1,
        ("notify_command.py", "edit_state", "DEFAULT_CONFIG_PATH"): 1,
        ("plan_execution_runtime.py", "save_plan_execution_state", "runtime_path"): 1,
        ("policy_command.py", "apply_profile", "POLICY_PATH"): 1,
        ("policy_command.py", "apply_profile", "NOTIFY_PATH"): 1,
        ("post_session_command.py", "edit_config", "CONFIG_PATH"): 1,
        ("stack_profile_command.py", "apply_state", "MODEL_ROUTING_PATH"): 1,
        ("stack_profile_command.py", "apply_state", "telemetry_path"): 1,
        ("stack_profile_command.py", "apply_state", "post_path"): 1,
        ("stack_profile_command.py", "apply_state", "policy_path"): 1,
        ("stack_profile_command.py", "apply_state", "notify_path"): 1,
        ("stack_profile_command.py", "apply_state", "STATE_PATH"): 1,
        ("telemetry_command.py", "edit_state", "CONFIG_PATH"): 1,
        ("tui_config.py", "ensure_execution_sidebar", "config_path.expanduser()"): 1,
    }
)

# Exact non-candidate state, cache, backup, plugin, and LaunchAgent operations.
# A new primitive sink in a production config writer must be classified here.
EXEMPT_PRIMITIVE_SINKS = Counter(
    {
        ("auto_slash_command.py", "_append_audit", "helper.append_exempt_text_line", "AUDIT_DEFAULT"): 1,
        ("config_command.py", "ensure_manifest", "path.mkdir", "BACKUP_DIR"): 1,
        ("config_command.py", "ensure_manifest", "path.write_text", "MANIFEST_PATH"): 1,
        ("config_command.py", "save_manifest", "path.write_text", "MANIFEST_PATH"): 1,
        ("config_command.py", "command_backup", "path.mkdir", "target_dir"): 1,
        ("config_command.py", "command_backup", "shutil.copy2", "dst"): 1,
        ("gateway_command.py", "_write_gateway_smoke_cache", "path.mkdir", "cache_dir"): 1,
        ("gateway_command.py", "_write_gateway_smoke_cache", "path.chmod", "cache_dir"): 1,
        ("gateway_command.py", "_write_gateway_smoke_cache", "tempfile.mkstemp", "cache_dir"): 1,
        ("gateway_command.py", "_write_gateway_smoke_cache", "os.replace", "path"): 1,
        ("gateway_command.py", "_write_gateway_smoke_cache", "path.chmod", "path"): 1,
        ("gateway_command.py", "_write_gateway_smoke_cache", "path.unlink", "temporary_path"): 1,
        ("gateway_command.py", "_invalidate_gateway_smoke_cache", "path.unlink", "path"): 1,
        ("gateway_command.py", "gateway_mistake_ledger_summary", "os.open", "path"): 1,
        ("gateway_command.py", "command_recover_memory/save_pane_session_cache", "path.mkdir", "pane_session_cache_path.parent"): 1,
        ("gateway_command.py", "command_recover_memory/save_pane_session_cache", "path.write_text", "pane_session_cache_path"): 1,
        ("gateway_command.py", "command_recover_memory_watch/save_state", "path.mkdir", "runtime_dir"): 1,
        ("gateway_command.py", "command_recover_memory_watch/save_state", "path.write_text", "state_path"): 1,
        ("gateway_command.py", "command_protection", "path.mkdir", "pane_cache_path.parent"): 1,
        ("gateway_command.py", "command_protection", "path.write_text", "pane_cache_path"): 1,
        ("gateway_command.py", "command_protection", "path.mkdir", "launch_dir"): 1,
        ("gateway_command.py", "command_protection", "path.mkdir", "log_dir"): 1,
        ("gateway_command.py", "command_protection", "path.write_text", "plist_path"): 1,
        ("hooks_command.py", "write_audit_log", "helper.append_exempt_text_line", "HOOK_LOG_PATH"): 1,
    }
)

EXPECTED_SHELL_SINKS = Counter(
    {
        ("setup_dual_opencode.sh", 'mkdir -p "$OPENCODE_CONFIG_DIR"'): 1,
        ("setup_dual_opencode.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-move --source "$OPENCODE_CONFIG_DIR/my_opencode/runtime/plan_execution.json" --target "$MY_OPENCODE_REPO/runtime/plan_execution.json"'): 1,
        ("setup_dual_opencode.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-link --link "$OPENCODE_CONFIG_DIR/my_opencode" --target "$MY_OPENCODE_REPO"'): 1,
        ("setup_dual_opencode.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-link --link "$OPENCODE_CONFIG_DIR/opencode.json" --target "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json"'): 1,
        ("setup_dual_opencode.sh", 'mkdir -p "$OHMY_CONFIG_HOME/opencode"'): 1,
        ("setup_dual_opencode.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-json --path "$OHMY_CONFIG_HOME/opencode/opencode.json" --content \'{"$schema":"https://opencode.ai/config.json","plugin":["oh-my-opencode@latest"]}\''): 1,
        ("setup_dual_opencode.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-json --path "$OHMY_CONFIG_HOME/opencode/oh-my-opencode.json" --source "$OPENCODE_CONFIG_DIR/oh-my-opencode.json"'): 1,
        ("setup_dual_opencode.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-json --path "$OHMY_CONFIG_HOME/opencode/oh-my-opencode.json" --content \'{"$schema":"https://raw.githubusercontent.com/code-yeongyu/oh-my-opencode/dev/assets/oh-my-opencode.schema.json"}\''): 1,
        ("setup_dual_opencode.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-line --path "$ZSHRC_FILE" --line "$ALIAS_LINE" --if-missing'): 1,
        ("setup_local_dev_symlinks.sh", 'mkdir -p "$OPENCODE_CONFIG_DIR"'): 1,
        ("setup_local_dev_symlinks.sh", 'mkdir -p "$OPENCODE_CONFIG_DIR/agent"'): 1,
        ("setup_local_dev_symlinks.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-link --link "$OPENCODE_CONFIG_DIR/my_opencode" --target "$MY_OPENCODE_REPO"'): 1,
        ("setup_local_dev_symlinks.sh", 'python3 "$SCRIPT_DIR/config_layering.py" provision-link --link "$OPENCODE_CONFIG_DIR/opencode.json" --target "$OPENCODE_CONFIG_DIR/my_opencode/opencode.json"'): 1,
        ("setup_local_dev_symlinks.sh", 'ln -sfn "$AGENTS_LINK_TARGET" "$MY_OPENCODE_REPO/AGENTS.md"'): 1,
        ("setup_local_dev_symlinks.sh", 'ln -sfn "$agent_file" "$OPENCODE_CONFIG_DIR/agent/$(basename "$agent_file")"'): 1,
    }
)


@dataclass(frozen=True)
class Analysis:
    transactions: Counter[tuple[str, str, str, str]]
    participants: Counter[tuple[str, str, str]]
    sinks: Counter[tuple[str, str, str, str]]


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


class WriterVisitor(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.functions: list[str] = []
        self.transactions: Counter[tuple[str, str, str, str]] = Counter()
        self.participants: Counter[tuple[str, str, str]] = Counter()
        self.sinks: Counter[tuple[str, str, str, str]] = Counter()

    @property
    def function(self) -> str:
        return "/".join(self.functions) or "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _record_sink(self, kind: str, destination: ast.AST | None) -> None:
        rendered = ast.unparse(destination) if destination is not None else "<missing>"
        self.sinks[(self.filename, self.function, kind, rendered)] += 1

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _name(node.func)
        first = ast.unparse(node.args[0]) if node.args else "<missing>"
        if call_name in TRANSACTION_APIS:
            self.transactions[
                (self.filename, self.function, call_name, first)
            ] += 1
        elif call_name == "ConfigFileParticipant":
            self.participants[(self.filename, self.function, first)] += 1
        elif call_name in HELPER_SINK_APIS:
            self._record_sink(f"helper.{call_name}", node.args[0] if node.args else None)

        function = node.func
        if isinstance(function, ast.Attribute):
            owner = function.value
            if isinstance(owner, ast.Name) and owner.id == "os" and function.attr in {
                "open",
                "replace",
                "rename",
                "unlink",
                "symlink",
                "link",
                "mkdir",
                "rmdir",
                "chmod",
            }:
                index = 1 if function.attr in {"replace", "rename", "symlink", "link"} else 0
                self._record_sink(
                    f"os.{function.attr}",
                    node.args[index] if len(node.args) > index else None,
                )
            elif isinstance(owner, ast.Name) and owner.id == "shutil" and function.attr in {
                "copy",
                "copy2",
                "copyfile",
                "move",
            }:
                self._record_sink(
                    f"shutil.{function.attr}",
                    node.args[1] if len(node.args) > 1 else None,
                )
            elif isinstance(owner, ast.Name) and owner.id == "tempfile" and function.attr in {
                "mkstemp",
                "NamedTemporaryFile",
            }:
                directory = next(
                    (item.value for item in node.keywords if item.arg == "dir"),
                    None,
                )
                self._record_sink(f"tempfile.{function.attr}", directory)
            elif function.attr == "open" and not (
                isinstance(owner, ast.Name) and owner.id in {"os", "tempfile"}
            ):
                mode = (
                    node.args[0].value
                    if node.args and isinstance(node.args[0], ast.Constant)
                    else None
                )
                if mode is None or any(flag in str(mode) for flag in "wax+"):
                    self._record_sink("path.open", owner)
            elif function.attr in {
                "write_text",
                "write_bytes",
                "mkdir",
                "unlink",
                "symlink_to",
                "rename",
                "replace",
                "touch",
                "chmod",
                "rmdir",
            } and (function.attr != "replace" or len(node.args) == 1):
                self._record_sink(f"path.{function.attr}", owner)
        elif isinstance(function, ast.Name) and function.id == "open":
            mode = (
                node.args[1].value
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                else None
            )
            if mode is None or any(flag in str(mode) for flag in "wax+"):
                self._record_sink("open", node.args[0] if node.args else None)
        self.generic_visit(node)


def analyze_python(path: Path) -> Analysis:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = WriterVisitor(path.name)
    visitor.visit(tree)
    return Analysis(visitor.transactions, visitor.participants, visitor.sinks)


def shell_logical_lines(path: Path) -> list[str]:
    logical: list[str] = []
    buffer = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        buffer += (" " if buffer else "") + stripped.rstrip("\\").rstrip()
        if stripped.endswith("\\"):
            continue
        if buffer:
            logical.append(buffer)
        buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def shell_sinks(path: Path) -> Counter[tuple[str, str]]:
    found: Counter[tuple[str, str]] = Counter()
    mutation = re.compile(r"^(?:command\s+)?(?:mkdir|ln|cp|mv|rm|install|touch|tee|cat)\b")
    provision = re.compile(r"config_layering\.py\"?\s+provision-(?:link|move|json|line)\b")
    redirect = re.compile(r"(^|[^0-9&-])(?:>>|>)\s*(?!&[0-9])")
    for line in shell_logical_lines(path):
        if line.startswith("#") or not line:
            continue
        if mutation.search(line) or provision.search(line) or redirect.search(line):
            found[(path.name, line)] += 1
    return found


def load_global_sink_manifest() -> tuple[Counter[tuple], list[str]]:
    problems: list[str] = []
    expected: Counter[tuple] = Counter()
    try:
        payload = json.loads(GLOBAL_SINK_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return expected, [f"unable to load global sink manifest: {error}"]
    if not isinstance(payload, list):
        return expected, ["global sink manifest root must be an array"]
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            problems.append(f"global sink manifest row {index} must be an object")
            continue
        classification = item.get("classification")
        if classification not in GLOBAL_SINK_CLASSIFICATIONS:
            problems.append(
                f"global sink manifest row {index} has invalid classification: "
                f"{classification}"
            )
            continue
        count = item.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            problems.append(f"global sink manifest row {index} has invalid count")
            continue
        language = item.get("language")
        if language == "python":
            key = (
                "python",
                item.get("file"),
                item.get("function"),
                item.get("kind"),
                item.get("destination"),
            )
        elif language == "shell":
            key = ("shell", item.get("file"), item.get("command"))
        else:
            problems.append(
                f"global sink manifest row {index} has invalid language: {language}"
            )
            continue
        if any(not isinstance(value, str) or not value for value in key):
            problems.append(f"global sink manifest row {index} has empty identity fields")
            continue
        expected[key] += count
    return expected, problems


def _counter_diff(
    label: str,
    actual: Counter[tuple],
    expected: Counter[tuple],
) -> list[str]:
    problems: list[str] = []
    for item, count in sorted((actual - expected).items()):
        problems.append(f"unmatched {label} ({count}x): {item}")
    for item, count in sorted((expected - actual).items()):
        problems.append(f"stale {label} exemption ({count}x): {item}")
    return problems


def inventory(*, extra_python_paths: tuple[Path, ...] = ()) -> dict[str, object]:
    transactions: Counter[tuple[str, str, str, str]] = Counter()
    participants: Counter[tuple[str, str, str]] = Counter()
    sinks: Counter[tuple[str, str, str, str]] = Counter()
    discovered: set[str] = set()
    problems: list[str] = []
    global_sinks: Counter[tuple] = Counter()

    python_paths = [*sorted(SCRIPTS_DIR.glob("*.py")), *extra_python_paths]
    for path in python_paths:
        if path.name in {Path(__file__).name, "selftest.py"}:
            continue
        analysis = analyze_python(path)
        global_sinks.update(
            {
                ("python", *identity): count
                for identity, count in analysis.sinks.items()
            }
        )
        if analysis.transactions or analysis.participants:
            if path.name != "config_layering.py":
                discovered.add(path.name)
            if path.name not in TRANSACTIONAL_WRITERS and path.name != "config_layering.py":
                problems.append(
                    f"unexpected transactional writer requires classification: {path.name}"
                )
        if path.name in TRANSACTIONAL_WRITERS:
            transactions.update(analysis.transactions)
            participants.update(analysis.participants)
            sinks.update(analysis.sinks)
            transaction_functions = {
                (filename, function)
                for filename, function, _api, _argument in analysis.transactions
            }
            for filename, function, _destination in analysis.participants:
                if (filename, function) not in transaction_functions:
                    problems.append(
                        "transaction participant is not attached in its function: "
                        f"{filename}:{function}"
                    )

    missing_modules = sorted(TRANSACTIONAL_WRITERS - discovered)
    if missing_modules:
        problems.append(
            "manifest writers missing transaction callsites: "
            + ", ".join(missing_modules)
        )
    problems.extend(
        _counter_diff("transaction callsite", transactions, EXPECTED_TRANSACTION_CALLS)
    )
    problems.extend(
        _counter_diff("direct participant", participants, EXPECTED_PARTICIPANTS)
    )
    problems.extend(
        _counter_diff("primitive sink", sinks, EXEMPT_PRIMITIVE_SINKS)
    )

    shell_actual: Counter[tuple[str, str]] = Counter()
    for name in {item[0] for item in EXPECTED_SHELL_SINKS}:
        shell_actual.update(shell_sinks(SCRIPTS_DIR / name))
    problems.extend(
        _counter_diff("provisioner sink", shell_actual, EXPECTED_SHELL_SINKS)
    )

    for path in sorted(SCRIPTS_DIR.glob("*.sh")):
        global_sinks.update(
            {
                ("shell", *identity): count
                for identity, count in shell_sinks(path).items()
            }
        )
    global_expected, manifest_problems = load_global_sink_manifest()
    problems.extend(manifest_problems)
    problems.extend(_counter_diff("global sink", global_sinks, global_expected))

    return {
        "result": "PASS" if not problems else "FAIL",
        "manifest": sorted(TRANSACTIONAL_WRITERS),
        "discovered": sorted(discovered),
        "transaction_calls": sum(transactions.values()),
        "direct_participants": sum(participants.values()),
        "primitive_exemptions": sum(sinks.values()),
        "provisioner_sinks": sum(shell_actual.values()),
        "global_sinks": sum(global_sinks.values()),
        "problems": problems,
    }


def main() -> int:
    report = inventory()
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
