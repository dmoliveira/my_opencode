from __future__ import annotations

import ast
import collections
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bounded_subprocess import OPERATION_CLASSES


@dataclass(frozen=True)
class DirectCallKey:
    file: str
    function: str
    executable: str
    explicit_timeout: bool


@dataclass(frozen=True)
class DirectCallDisposition:
    category: str
    rationale: str
    count: int


DIRECT_CALL_DISPOSITIONS: dict[DirectCallKey, DirectCallDisposition] = {
    DirectCallKey(
        "autopilot_command.py", "infer_touched_paths", "git", True
    ): DirectCallDisposition(
        "already_bounded",
        "existing repository and dynamic touched-path Git probes have explicit five-second timeouts",
        2,
    ),
    DirectCallKey("image_command.py", "active_repo_root", "git", True): DirectCallDisposition(
        "already_bounded",
        "existing active-repository probe already has an explicit timeout",
        1,
    ),
    DirectCallKey("changes_command.py", "_run_git", "git", False): DirectCallDisposition(
        "excluded_long_read",
        "user-requested full diff generation can be legitimately long",
        1,
    ),
    DirectCallKey(
        "pr_review_analyzer.py", "analyze_git_range", "git", False
    ): DirectCallDisposition(
        "excluded_long_read",
        "user-requested full review diff is outside guard/probe metadata scope",
        1,
    ),
    DirectCallKey("release_train_engine.py", "run_git", "git", False): DirectCallDisposition(
        "excluded_long_read",
        "wrapper is retained only for the arbitrary release range log",
        1,
    ),
    DirectCallKey("hotfix_command.py", "open_followup_issue", "gh", False): DirectCallDisposition(
        "excluded_mutation",
        "GitHub issue creation is an intentional mutating operation",
        1,
    ),
    DirectCallKey("release_train_command.py", "command_publish", "git", False): DirectCallDisposition(
        "excluded_mutation",
        "tag creation and push are intentional release mutations",
        2,
    ),
    DirectCallKey("release_train_command.py", "command_publish", "gh", False): DirectCallDisposition(
        "excluded_mutation",
        "GitHub release creation is an intentional mutation",
        1,
    ),
    DirectCallKey("ship_command.py", "_assign_reviewers", "gh", False): DirectCallDisposition(
        "excluded_mutation",
        "reviewer assignment mutates pull-request state",
        1,
    ),
    DirectCallKey("ship_command.py", "_command_create_pr", "gh", False): DirectCallDisposition(
        "excluded_mutation",
        "pull-request creation is an intentional mutation",
        1,
    ),
    DirectCallKey(
        "selftest.py", "initialize_validation_git_fixture", "git", False
    ): DirectCallDisposition(
        "excluded_test_fixture",
        "deterministic selftest Git fixture setup is not production guard execution",
        5,
    ),
    DirectCallKey("selftest.py", "main", "git", False): DirectCallDisposition(
        "excluded_test_fixture",
        "selftest Git fixture and command assertions are not production guard execution",
        40,
    ),
}


RECOGNIZED_BOUNDED_CALLS = {
    "run_bounded",
    "_git_bytes",
    "run_git_probe",
    "run_git",
    "_run_git",
    "run_text",
}


BOUNDED_WRAPPER_DEFINITIONS = {
    ("completion_gates.py", "_git_bytes"),
    ("release_train_engine.py", "run_git_probe"),
    ("hotfix_runtime.py", "run_git"),
    ("knowledge_capture_pipeline.py", "_run_git"),
    ("session_digest.py", "run_text"),
}


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _is_direct_subprocess_run(call: ast.Call) -> bool:
    if (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "subprocess"
        and call.func.attr == "run"
    ):
        return True
    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Call)
        and call.func.attr == "run"
    ):
        return False
    imported = call.func.value
    return bool(
        isinstance(imported.func, ast.Name)
        and imported.func.id == "__import__"
        and imported.args
        and isinstance(imported.args[0], ast.Constant)
        and imported.args[0].value == "subprocess"
    )


def _literal_executable(command: ast.AST) -> str | None:
    if not isinstance(command, (ast.List, ast.Tuple)):
        return None
    values = command.elts
    if not values or not isinstance(values[0], ast.Constant):
        return None
    executable = values[0].value
    return executable if executable in {"git", "gh"} else None


def _assigned_loop_executable(
    call: ast.Call,
    parents: dict[ast.AST, ast.AST],
) -> str | None:
    if not call.args or not isinstance(call.args[0], ast.Name):
        return None
    command_name = call.args[0].id
    current = parents.get(call)
    loop: ast.For | None = None
    scope: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    while current is not None:
        if (
            loop is None
            and isinstance(current, ast.For)
            and isinstance(current.target, ast.Name)
            and current.target.id == command_name
        ):
            loop = current
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = current
            break
        current = parents.get(current)
    if loop is None or scope is None or not isinstance(loop.iter, ast.Name):
        return None

    collection_name = loop.iter.id
    for node in ast.walk(scope):
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == collection_name
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return None
        resolved = [_literal_executable(item) for item in node.value.elts]
        executables = {item for item in resolved if item is not None}
        if len(executables) == 1 and all(item is not None for item in resolved):
            return next(iter(executables))
        return None
    return None


def _resolved_executable(
    call: ast.Call,
    parents: dict[ast.AST, ast.AST],
) -> str | None:
    if not call.args or not isinstance(call.args[0], (ast.List, ast.Tuple)):
        return _assigned_loop_executable(call, parents)
    return _literal_executable(call.args[0])


def _parent_functions(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _containing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return "module"


class BoundedSubprocessInventoryTest(unittest.TestCase):
    def test_direct_git_github_calls_are_exhaustively_dispositioned(self) -> None:
        discovered: collections.Counter[DirectCallKey] = collections.Counter()
        for path in sorted(SCRIPTS_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents = _parent_functions(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not _is_direct_subprocess_run(node):
                    continue
                executable = _resolved_executable(node, parents)
                if executable is None:
                    continue
                discovered[
                    DirectCallKey(
                        path.name,
                        _containing_function(node, parents),
                        executable,
                        any(keyword.arg == "timeout" for keyword in node.keywords),
                    )
                ] += 1

        expected = collections.Counter(
            {key: disposition.count for key, disposition in DIRECT_CALL_DISPOSITIONS.items()}
        )
        self.assertEqual(expected, discovered)
        for key, disposition in DIRECT_CALL_DISPOSITIONS.items():
            self.assertTrue(disposition.rationale)
            if disposition.category == "already_bounded":
                self.assertTrue(key.explicit_timeout)
            else:
                self.assertFalse(key.explicit_timeout)

    def test_registered_operations_are_each_used_once(self) -> None:
        operations: collections.Counter[str] = collections.Counter()
        wrappers_with_dynamic_operation: set[tuple[str, str]] = set()
        for path in sorted(SCRIPTS_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents = _parent_functions(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call_name = _call_name(node)
                if call_name not in RECOGNIZED_BOUNDED_CALLS:
                    continue
                operation = next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "operation"),
                    None,
                )
                if isinstance(operation, ast.Constant) and isinstance(
                    operation.value, str
                ):
                    operations[operation.value] += 1
                elif isinstance(operation, ast.Name) and call_name == "run_bounded":
                    wrappers_with_dynamic_operation.add(
                        (path.name, _containing_function(node, parents))
                    )

        self.assertEqual(
            collections.Counter({operation: 1 for operation in OPERATION_CLASSES}),
            operations,
        )
        self.assertEqual(BOUNDED_WRAPPER_DEFINITIONS, wrappers_with_dynamic_operation)

    def test_disposition_sets_are_disjoint(self) -> None:
        categories = collections.defaultdict(set)
        for key, disposition in DIRECT_CALL_DISPOSITIONS.items():
            categories[disposition.category].add(key)
        category_names = sorted(categories)
        for index, left_name in enumerate(category_names):
            for right_name in category_names[index + 1 :]:
                self.assertTrue(categories[left_name].isdisjoint(categories[right_name]))


if __name__ == "__main__":
    unittest.main()
