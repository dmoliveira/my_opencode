from __future__ import annotations

import json
import multiprocessing
import os
import stat
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import config_layering as layering  # noqa: E402
from config_layering import (  # noqa: E402
    LOCK_OWNER_TOKEN,
    MAX_SAFE_INTEGER,
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    STAGE_PREFIX,
    ConfigFileParticipant,
    ConfigTransactionError,
    _load_json_or_jsonc,
    _acquire_lock,
    _lock_name,
    _lock_registry,
    _release_lock,
    append_exempt_text_line,
    edit_config_batch,
    edit_layered_config,
    provision_config_move,
    provision_config_json,
)
from check_config_writer_inventory import inventory  # noqa: E402
from plan_execution_runtime import save_plan_execution_state  # noqa: E402


def _write_config(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    path.parent.chmod(PRIVATE_DIRECTORY_MODE)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(PRIVATE_FILE_MODE)


def _contention_writer(
    config_path: str,
    home: str,
    ready_path: str,
    go_path: str,
    domain: str,
    output: object,
) -> None:
    try:
        os.environ["HOME"] = home
        os.environ["OPENCODE_CONFIG_PATH"] = config_path
        Path(ready_path).write_text("ready\n", encoding="utf-8")
        deadline = time.monotonic() + 10
        while not Path(go_path).exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("barrier timed out")
            time.sleep(0.01)

        def mutate(config: dict[str, object]) -> None:
            domains = config.setdefault("domains", {})
            assert isinstance(domains, dict)
            domains[domain] = {"writer": domain}

        edit_layered_config(mutate)
        output.put((domain, "PASS"))
    except BaseException as error:  # pragma: no cover - surfaced by parent.
        output.put((domain, f"{type(error).__name__}:{error}"))


class LayeredConfigTransactionTest(unittest.TestCase):
    @contextmanager
    def isolated(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            home = root / "home"
            project = root / "project"
            home.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            project.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            old_home = os.environ.get("HOME")
            old_override = os.environ.get("OPENCODE_CONFIG_PATH")
            old_runtime = os.environ.get("MY_OPENCODE_PLAN_RUNTIME_PATH")
            old_cwd = Path.cwd()
            os.environ["HOME"] = str(home)
            os.chdir(project)
            try:
                yield root, home, project
            finally:
                os.chdir(old_cwd)
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_override is None:
                    os.environ.pop("OPENCODE_CONFIG_PATH", None)
                else:
                    os.environ["OPENCODE_CONFIG_PATH"] = old_override
                if old_runtime is None:
                    os.environ.pop("MY_OPENCODE_PLAN_RUNTIME_PATH", None)
                else:
                    os.environ["MY_OPENCODE_PLAN_RUNTIME_PATH"] = old_runtime

    def test_strict_jsonc_parser_preserves_tokens_and_rejects_unsafe_values(self) -> None:
        with self.isolated() as (root, _home, _project):
            valid = root / "valid.jsonc"
            valid.write_text(
                '{\n  // line\n  "url": "https://example.test/a//b",\n'
                '  "marker": "/* literal */",\n  "items": [1, 2,],\n}\n',
                encoding="utf-8",
            )
            valid.chmod(PRIVATE_FILE_MODE)
            parsed = _load_json_or_jsonc(valid)
            self.assertEqual([1, 2], parsed["items"])
            self.assertEqual("/* literal */", parsed["marker"])

            invalid = {
                "empty_object_comma": "{,}",
                "empty_array_comma": "[, ]",
                "missing_value_comma": '{"value":,}',
                "fusion": '{"value": 1/* comment */2}',
                "unterminated": '{"value": 1 /* comment}',
                "duplicate": '{"value": 1, "value": 2}',
                "nan": '{"value": NaN}',
                "unsafe": f'{{"value": {MAX_SAFE_INTEGER + 1}}}',
                "root": "[]",
            }
            for name, content in invalid.items():
                with self.subTest(name=name):
                    path = root / f"{name}.jsonc"
                    path.write_text(content, encoding="utf-8")
                    path.chmod(PRIVATE_FILE_MODE)
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        _load_json_or_jsonc(path)

    def test_noop_preserves_exact_file_metadata(self) -> None:
        with self.isolated() as (root, _home, _project):
            config = root / "config.json"
            _write_config(config, {"value": 1})
            os.environ["OPENCODE_CONFIG_PATH"] = str(config)
            before_bytes = config.read_bytes()
            before = config.stat()
            result = edit_layered_config(lambda _data: None)
            after = config.stat()
            self.assertFalse(result.changed)
            self.assertFalse(result.committed)
            self.assertTrue(result.lock_released)
            self.assertEqual(before_bytes, config.read_bytes())
            self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
            self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
            self.assertEqual(stat.S_IMODE(before.st_mode), stat.S_IMODE(after.st_mode))

    def test_two_processes_preserve_disjoint_nested_updates(self) -> None:
        with self.isolated() as (root, home, _project):
            config = root / "config.json"
            _write_config(config, {"domains": {}, "unknown": {"keep": True}})
            context = multiprocessing.get_context("spawn")
            output = context.Queue()
            go = root / "go"
            processes = []
            for domain in ("alpha", "beta"):
                process_home = root / f"home-{domain}"
                process_home.mkdir(mode=PRIVATE_DIRECTORY_MODE)
                process = context.Process(
                    target=_contention_writer,
                    args=(
                        str(config),
                        str(process_home),
                        str(root / f"{domain}.ready"),
                        str(go),
                        domain,
                        output,
                    ),
                )
                process.start()
                processes.append(process)
            deadline = time.monotonic() + 15
            while not all((root / f"{domain}.ready").exists() for domain in ("alpha", "beta")):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            go.write_text("go\n", encoding="utf-8")
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(0, process.exitcode)
            self.assertEqual(
                {("alpha", "PASS"), ("beta", "PASS")},
                {output.get(timeout=1) for _ in processes},
            )
            payload = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual({"alpha", "beta"}, set(payload["domains"]))
            self.assertTrue(payload["unknown"]["keep"])

    def test_parent_and_final_symlinks_are_preserved(self) -> None:
        with self.isolated() as (root, home, project):
            repo = root / "repo"
            repo.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            target = repo / "opencode.json"
            _write_config(target, {"value": 1, "unknown": "keep"})
            config_dir = home / ".config" / "opencode"
            config_dir.mkdir(parents=True, mode=PRIVATE_DIRECTORY_MODE)
            link_parent = config_dir / "my_opencode"
            link_parent.symlink_to(repo, target_is_directory=True)
            link = config_dir / "opencode.json"
            link.symlink_to(link_parent / "opencode.json")
            os.environ.pop("OPENCODE_CONFIG_PATH", None)

            with mock.patch("config_layering._base_config_path", return_value=target):
                result = edit_layered_config(lambda data: data.update({"value": 2}))

            self.assertTrue(result.committed)
            self.assertTrue(link.is_symlink())
            self.assertTrue(link_parent.is_symlink())
            self.assertEqual(2, json.loads(target.read_text(encoding="utf-8"))["value"])
            self.assertEqual("keep", json.loads(target.read_text(encoding="utf-8"))["unknown"])
            self.assertFalse((project / ".opencode").exists())

    def test_pre_mutation_symlink_retarget_retries_but_mutates_once(self) -> None:
        with self.isolated() as (root, _home, _project):
            first = root / "first.json"
            second = root / "second.json"
            _write_config(first, {"value": 1})
            _write_config(second, {"value": 10})
            link = root / "config.json"
            link.symlink_to(first)
            os.environ["OPENCODE_CONFIG_PATH"] = str(link)
            injected = False
            calls = 0

            def inject(phase: str) -> None:
                nonlocal injected
                if phase == "after_target_locks" and not injected:
                    link.unlink()
                    link.symlink_to(second)
                    injected = True

            def mutate(data: dict[str, object]) -> None:
                nonlocal calls
                calls += 1
                data["value"] = int(data["value"]) + 1

            result = edit_layered_config(mutate, _failure_injector=inject)
            self.assertTrue(result.committed)
            self.assertEqual(1, calls)
            self.assertEqual(1, json.loads(first.read_text(encoding="utf-8"))["value"])
            self.assertEqual(11, json.loads(second.read_text(encoding="utf-8"))["value"])
            self.assertTrue(link.is_symlink())

    def test_post_mutation_symlink_change_fails_without_victim_write(self) -> None:
        with self.isolated() as (root, _home, _project):
            original = root / "original.json"
            victim = root / "victim.json"
            _write_config(original, {"value": 1})
            _write_config(victim, {"victim": True})
            link = root / "config.json"
            link.symlink_to(original)
            os.environ["OPENCODE_CONFIG_PATH"] = str(link)
            victim_before = victim.read_bytes()
            injected = False

            def inject(phase: str) -> None:
                nonlocal injected
                if phase == "after_stage_fsync" and not injected:
                    link.unlink()
                    link.symlink_to(victim)
                    injected = True

            with self.assertRaises(ConfigTransactionError) as raised:
                edit_layered_config(
                    lambda data: data.update({"value": 2}),
                    _failure_injector=inject,
                )
            self.assertEqual("config_snapshot_changed", raised.exception.reason_code)
            self.assertFalse(raised.exception.committed)
            self.assertEqual({"value": 1}, json.loads(original.read_text(encoding="utf-8")))
            self.assertEqual(victim_before, victim.read_bytes())
            self.assertFalse(any(item.name.startswith(STAGE_PREFIX) for item in root.iterdir()))

    def test_symlink_dotdot_components_follow_os_path_semantics(self) -> None:
        with self.isolated() as (root, _home, _project):
            safe = root / "safe"
            other = root / "other"
            inner = other / "inner"
            safe.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            inner.mkdir(parents=True, mode=PRIVATE_DIRECTORY_MODE)
            target = other / "config.json"
            decoy = safe / "config.json"
            _write_config(target, {"value": 1})
            _write_config(decoy, {"value": 99})

            outer_link = safe / "outer-link"
            outer_link.symlink_to(inner, target_is_directory=True)
            os.environ["OPENCODE_CONFIG_PATH"] = os.fspath(
                outer_link / ".." / "config.json"
            )
            edit_layered_config(lambda data: data.update({"value": 2}))
            self.assertEqual(2, json.loads(target.read_text())["value"])
            self.assertEqual(99, json.loads(decoy.read_text())["value"])

            raw_link = safe / "raw-link"
            raw_link.symlink_to("../other/inner/..", target_is_directory=True)
            os.environ["OPENCODE_CONFIG_PATH"] = os.fspath(raw_link / "config.json")
            edit_layered_config(lambda data: data.update({"value": 3}))
            self.assertEqual(3, json.loads(target.read_text())["value"])
            self.assertEqual(99, json.loads(decoy.read_text())["value"])

    def test_post_lock_same_union_retarget_fails_before_mutators(self) -> None:
        with self.isolated() as (root, _home, _project):
            layered = root / "a.json"
            shared = root / "b.json"
            third = root / "c.json"
            _write_config(layered, {"layered": 1})
            _write_config(shared, {"shared": 1})
            _write_config(third, {"third": 1})
            first_alias = root / "first-b.json"
            second_alias = root / "second-b.json"
            first_alias.symlink_to(shared)
            second_alias.symlink_to(shared)
            os.environ["OPENCODE_CONFIG_PATH"] = str(layered)
            calls: list[str] = []
            injected = False

            def inject(phase: str) -> None:
                nonlocal injected
                if phase == "after_target_locks" and not injected:
                    first_alias.unlink()
                    first_alias.symlink_to(layered)
                    injected = True

            participants = (
                ConfigFileParticipant(first_alias, lambda data: calls.append("first")),
                ConfigFileParticipant(second_alias, lambda data: calls.append("second")),
                ConfigFileParticipant(third, lambda data: calls.append("third")),
            )
            with self.assertRaises(ConfigTransactionError) as raised:
                edit_layered_config(
                    lambda data: calls.append("layered"),
                    direct_participants=participants,
                    _failure_injector=inject,
                )
            self.assertEqual("config_alias_collision", raised.exception.reason_code)
            self.assertEqual([], calls)
            self.assertEqual({"layered": 1}, json.loads(layered.read_text()))

    def test_ambiguous_darwin_case_alias_fails_before_mutation(self) -> None:
        with self.isolated() as (root, _home, _project), mock.patch(
            "config_layering.sys.platform", "darwin"
        ):
            calls: list[str] = []
            with self.assertRaises(ConfigTransactionError) as raised:
                edit_config_batch(
                    (
                        ConfigFileParticipant(
                            root / "Case.json", lambda data: calls.append("upper")
                        ),
                        ConfigFileParticipant(
                            root / "case.json", lambda data: calls.append("lower")
                        ),
                    )
                )
            self.assertEqual("config_alias_collision", raised.exception.reason_code)
            self.assertEqual([], calls)

    def test_destination_and_stage_swaps_fail_before_replacement(self) -> None:
        with self.isolated() as (root, _home, _project):
            config = root / "config.json"
            _write_config(config, {"value": 1})
            os.environ["OPENCODE_CONFIG_PATH"] = str(config)
            injected = False

            def swap_destination(phase: str) -> None:
                nonlocal injected
                if phase == "before_replace" and not injected:
                    replacement = root / "replacement.json"
                    _write_config(replacement, {"attacker": True})
                    os.replace(replacement, config)
                    injected = True

            with self.assertRaises(ConfigTransactionError) as raised:
                edit_layered_config(
                    lambda data: data.update({"value": 2}),
                    _failure_injector=swap_destination,
                )
            self.assertEqual("config_snapshot_changed", raised.exception.reason_code)
            self.assertEqual({"attacker": True}, json.loads(config.read_text()))
            self.assertFalse(any(item.name.startswith(STAGE_PREFIX) for item in root.iterdir()))

            _write_config(config, {"value": 1})
            swapped_stage: Path | None = None

            def swap_stage(phase: str) -> None:
                nonlocal swapped_stage
                if phase == "before_replace" and swapped_stage is None:
                    swapped_stage = next(root.glob(f"{STAGE_PREFIX}*"))
                    swapped_stage.unlink()
                    _write_config(swapped_stage, {"attacker": True})

            with self.assertRaises(ConfigTransactionError) as raised:
                edit_layered_config(
                    lambda data: data.update({"value": 2}),
                    _failure_injector=swap_stage,
                )
            self.assertEqual("config_stage_changed", raised.exception.reason_code)
            self.assertEqual({"value": 1}, json.loads(config.read_text()))
            assert swapped_stage is not None
            self.assertTrue(swapped_stage.exists())

    def test_stage_descriptors_close_on_success_failure_and_partial_commit(self) -> None:
        with self.isolated() as (root, _home, _project):
            success = root / "success.json"
            failure = root / "failure.json"
            first = root / "first.json"
            second = root / "second.json"
            for path in (success, failure, first, second):
                _write_config(path, {"value": 1})

            real_open = layering.os.open
            real_close = layering.os.close
            stage_opens: list[int] = []
            stage_closes: list[int] = []
            active_stage_fds: set[int] = set()

            def tracked_open(path, *args, **kwargs):
                descriptor = real_open(path, *args, **kwargs)
                if isinstance(path, str) and path.startswith(STAGE_PREFIX):
                    stage_opens.append(descriptor)
                    active_stage_fds.add(descriptor)
                return descriptor

            def tracked_close(descriptor: int) -> None:
                if descriptor in active_stage_fds:
                    stage_closes.append(descriptor)
                    active_stage_fds.remove(descriptor)
                real_close(descriptor)

            with mock.patch.object(
                layering.os,
                "open",
                side_effect=tracked_open,
            ), mock.patch.object(
                layering.os,
                "close",
                side_effect=tracked_close,
            ):
                self.assertTrue(
                    edit_config_batch(
                        (
                            ConfigFileParticipant(
                                success,
                                lambda data: data.update({"value": 2}),
                            ),
                        )
                    ).committed
                )

                def fail_before_replace(phase: str) -> None:
                    if phase == "before_replace":
                        raise RuntimeError("injected pre-replace failure")

                with self.assertRaises(ConfigTransactionError):
                    edit_config_batch(
                        (
                            ConfigFileParticipant(
                                failure,
                                lambda data: data.update({"value": 2}),
                            ),
                        ),
                        _failure_injector=fail_before_replace,
                    )

                replaced = 0

                def fail_after_first_replace(phase: str) -> None:
                    nonlocal replaced
                    if phase == "after_replace":
                        replaced += 1
                        if replaced == 1:
                            raise RuntimeError("injected partial commit")

                with self.assertRaises(ConfigTransactionError) as partial:
                    edit_config_batch(
                        (
                            ConfigFileParticipant(
                                first,
                                lambda data: data.update({"value": 2}),
                            ),
                            ConfigFileParticipant(
                                second,
                                lambda data: data.update({"value": 2}),
                            ),
                        ),
                        _failure_injector=fail_after_first_replace,
                    )
                self.assertEqual("partial_commit", partial.exception.reason_code)

            self.assertEqual(4, len(stage_opens))
            self.assertEqual(stage_opens, stage_closes)
            self.assertEqual(set(), active_stage_fds)
            self.assertFalse(
                any(item.name.startswith(STAGE_PREFIX) for item in root.iterdir())
            )

    def test_malformed_state_fails_closed_and_bool_number_change_commits(self) -> None:
        with self.isolated() as (root, _home, _project):
            malformed = root / "malformed.json"
            malformed.write_bytes(b"{\xff")
            malformed.chmod(PRIVATE_FILE_MODE)
            before = malformed.read_bytes()
            with self.assertRaises(ConfigTransactionError) as raised:
                edit_config_batch(
                    (
                        ConfigFileParticipant(
                            malformed, lambda data: data.update({"repaired": True})
                        ),
                    )
                )
            self.assertEqual("config_invalid_utf8", raised.exception.reason_code)
            self.assertEqual(before, malformed.read_bytes())

            typed = root / "typed.json"
            _write_config(typed, {"value": 1})
            result = edit_config_batch(
                (ConfigFileParticipant(typed, lambda data: data.update({"value": True})),)
            )
            self.assertTrue(result.committed)
            self.assertIs(True, json.loads(typed.read_text())["value"])

    def test_first_replace_failure_has_replace_phase_and_ordered_results(self) -> None:
        with self.isolated() as (root, _home, _project):
            first = root / "a.json"
            second = root / "b.json"
            _write_config(first, {"value": 1})
            _write_config(second, {"value": 1})
            original_replace = os.replace

            def fail_stage_replace(source, target, *args, **kwargs):
                if os.fspath(source).startswith(STAGE_PREFIX):
                    raise OSError(5, "injected replacement failure")
                return original_replace(source, target, *args, **kwargs)

            with mock.patch("config_layering.os.replace", side_effect=fail_stage_replace):
                with self.assertRaises(ConfigTransactionError) as raised:
                    edit_config_batch(
                        (
                            ConfigFileParticipant(
                                second, lambda data: data.update({"value": 2})
                            ),
                            ConfigFileParticipant(
                                first, lambda data: data.update({"value": 2})
                            ),
                        )
                    )
            error = raised.exception
            self.assertEqual("config_replace_failed", error.reason_code)
            self.assertEqual("replace", error.phase)
            self.assertFalse(error.committed)
            self.assertEqual(
                [str(second.resolve()), str(first.resolve())],
                [str(item.canonical_path) for item in error.file_results],
            )
            self.assertEqual([False, False], [item.committed for item in error.file_results])

    def test_plan_runtime_compare_and_swap_rejects_stale_snapshot(self) -> None:
        with self.isolated() as (root, _home, _project):
            config = root / "config.json"
            runtime = root / "runtime.json"
            _write_config(config, {})
            _write_config(runtime, {"version": 1})
            os.environ["OPENCODE_CONFIG_PATH"] = str(config)
            os.environ["MY_OPENCODE_PLAN_RUNTIME_PATH"] = str(runtime)
            save_plan_execution_state(
                {},
                config,
                {"version": 2},
                expected_runtime={"version": 1},
            )
            with self.assertRaises(ConfigTransactionError) as raised:
                save_plan_execution_state(
                    {},
                    config,
                    {"version": 3},
                    expected_runtime={"version": 1},
                )
            self.assertEqual("plan_runtime_stale", raised.exception.reason_code)
            self.assertEqual({"version": 2}, json.loads(runtime.read_text()))

    def test_lock_token_swap_safety_and_reverse_release_order(self) -> None:
        with self.isolated() as (root, _home, _project):
            registry = _lock_registry()
            missing_token_path = registry / f"test-{uuid.uuid4().hex}.lock"
            lock = _acquire_lock(missing_token_path, time.monotonic() + 1)
            (missing_token_path / LOCK_OWNER_TOKEN).unlink()
            with self.assertRaises(ConfigTransactionError) as raised:
                _release_lock(lock)
            self.assertEqual("config_lock_release_failed", raised.exception.reason_code)
            missing_token_path.rmdir()

            swapped_path = registry / f"test-{uuid.uuid4().hex}.lock"
            displaced = registry / f"test-{uuid.uuid4().hex}.displaced"
            lock = _acquire_lock(swapped_path, time.monotonic() + 1)
            swapped_path.rename(displaced)
            swapped_path.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            replacement_token = swapped_path / LOCK_OWNER_TOKEN
            replacement_token.write_bytes(b"f" * 64 + b"\n")
            replacement_token.chmod(PRIVATE_FILE_MODE)
            with self.assertRaises(ConfigTransactionError):
                _release_lock(lock)
            self.assertTrue(replacement_token.exists())
            replacement_token.unlink()
            swapped_path.rmdir()
            (displaced / LOCK_OWNER_TOKEN).unlink()
            displaced.rmdir()

            config = root / "config.json"
            _write_config(config, {"value": 1})
            acquired: list[Path] = []
            released: list[Path] = []
            original_acquire = _acquire_lock
            original_release = _release_lock

            def record_acquire(path: Path, deadline: float):
                owned = original_acquire(path, deadline)
                acquired.append(path)
                return owned

            def record_release(owned, failure_injector=None):
                released.append(owned.path)
                return original_release(owned, failure_injector)

            with mock.patch(
                "config_layering._acquire_lock", side_effect=record_acquire
            ), mock.patch("config_layering._release_lock", side_effect=record_release):
                edit_config_batch(
                    (
                        ConfigFileParticipant(
                            config, lambda data: data.update({"value": 2})
                        ),
                    )
                )
            self.assertEqual(list(reversed(acquired)), released)

    def test_serialized_move_and_exempt_append_reject_candidate_alias(self) -> None:
        with self.isolated() as (root, _home, _project):
            source = root / "source.json"
            target = root / "nested" / "target.json"
            _write_config(source, {"value": 1})
            self.assertTrue(provision_config_move(source, target))
            self.assertFalse(source.exists())
            self.assertEqual({"value": 1}, json.loads(target.read_text()))

            config = root / "config.json"
            _write_config(config, {"value": 1})
            os.environ["OPENCODE_CONFIG_PATH"] = str(config)
            with self.assertRaises(ConfigTransactionError) as raised:
                append_exempt_text_line(config, "not-json")
            self.assertEqual("config_alias_collision", raised.exception.reason_code)
            self.assertEqual({"value": 1}, json.loads(config.read_text()))

            audit = root / "audit.jsonl"
            self.assertTrue(append_exempt_text_line(audit, '{"event":1}'))
            self.assertFalse(
                append_exempt_text_line(audit, '{"event":1}', if_missing=True)
            )
            self.assertEqual(['{"event":1}'], audit.read_text().splitlines())

    def test_provision_helpers_reject_all_candidate_aliases_and_move_swap(self) -> None:
        with self.isolated() as (root, _home, project):
            base = root / "base" / "opencode.json"
            override = project / ".opencode" / "my_opencode.json"
            _write_config(base, {"base": True})
            _write_config(override, {"override": True})
            os.environ.pop("OPENCODE_CONFIG_PATH", None)
            alias = root / "alias.json"
            alias.symlink_to(base)
            base_before = base.read_bytes()

            with mock.patch("config_layering._base_config_path", return_value=base):
                with self.assertRaises(ConfigTransactionError) as raised:
                    provision_config_json(alias, {"victim": True})
                self.assertEqual("config_alias_collision", raised.exception.reason_code)
                self.assertEqual(base_before, base.read_bytes())

                source = root / "runtime.json"
                _write_config(source, {"runtime": True})
                with self.assertRaises(ConfigTransactionError) as raised:
                    provision_config_move(source, alias)
                self.assertEqual("config_alias_collision", raised.exception.reason_code)
                self.assertTrue(source.exists())
                self.assertEqual(base_before, base.read_bytes())

                move_target = root / "moved.json"
                with self.assertRaises(ConfigTransactionError) as raised:
                    provision_config_move(base, move_target)
                self.assertEqual("config_alias_collision", raised.exception.reason_code)
                self.assertEqual(base_before, base.read_bytes())

            target = root / "target.json"
            _write_config(target, {"target": 1})
            injected = False

            def swap_target(phase: str) -> None:
                nonlocal injected
                if phase == "before_provision_move" and not injected:
                    replacement = root / "attacker.json"
                    _write_config(replacement, {"attacker": True})
                    os.replace(replacement, target)
                    injected = True

            with self.assertRaises(ConfigTransactionError) as raised:
                provision_config_move(
                    source,
                    target,
                    _failure_injector=swap_target,
                )
            self.assertEqual("config_snapshot_changed", raised.exception.reason_code)
            self.assertTrue(source.exists())
            self.assertEqual({"attacker": True}, json.loads(target.read_text()))

    def test_exempt_append_reports_partial_and_release_commit_metadata(self) -> None:
        with self.isolated() as (root, _home, _project):
            config = root / "config.json"
            _write_config(config, {"value": 1})
            os.environ["OPENCODE_CONFIG_PATH"] = str(config)
            audit = root / "partial.jsonl"
            payload = b"abcdef\n"
            payload_calls = 0
            original_write = os.write

            def partial_write(descriptor: int, data) -> int:
                nonlocal payload_calls
                raw = bytes(data)
                if raw in {payload, payload[2:]}:
                    payload_calls += 1
                    if payload_calls == 1:
                        return original_write(descriptor, raw[:2])
                    raise OSError(5, "injected partial append")
                return original_write(descriptor, data)

            with mock.patch("config_layering.os.write", side_effect=partial_write):
                with self.assertRaises(ConfigTransactionError) as raised:
                    append_exempt_text_line(audit, "abcdef")
            error = raised.exception
            self.assertEqual("committed_durability_uncertain", error.reason_code)
            self.assertTrue(error.committed)
            self.assertEqual("uncertain", error.durability)
            self.assertEqual(b"ab", audit.read_bytes())

            release_audit = root / "release.jsonl"
            with self.assertRaises(ConfigTransactionError) as raised:
                append_exempt_text_line(
                    release_audit,
                    "committed",
                    _failure_injector=lambda phase: (
                        (_ for _ in ()).throw(RuntimeError("release sync"))
                        if phase == "after_lock_remove"
                        else None
                    ),
                )
            error = raised.exception
            self.assertEqual("committed_lock_release_failed", error.reason_code)
            self.assertTrue(error.committed)
            self.assertEqual("synced", error.durability)
            self.assertTrue(error.lock_released)
            self.assertEqual("committed\n", release_audit.read_text())

    def test_inventory_rejects_unmatched_direct_config_writer_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            fixture = Path(raw_tmp) / "untracked_config_writer.py"
            fixture.write_text(
                "from pathlib import Path\n"
                "import os\n"
                "Path(os.environ['OPENCODE_CONFIG_PATH']).write_text('{}')\n",
                encoding="utf-8",
            )
            report = inventory(extra_python_paths=(fixture,))
            self.assertEqual("FAIL", report["result"])
            self.assertTrue(
                any(
                    "unmatched global sink" in problem
                    and "untracked_config_writer.py" in problem
                    for problem in report["problems"]
                )
            )

    def test_hardlink_and_broken_symlink_fail_closed(self) -> None:
        with self.isolated() as (root, _home, _project):
            victim = root / "victim.json"
            _write_config(victim, {"victim": True})
            victim_before = victim.read_bytes()
            for attack in ("hardlink", "broken"):
                with self.subTest(attack=attack):
                    candidate = root / f"{attack}.json"
                    if attack == "hardlink":
                        os.link(victim, candidate)
                    else:
                        candidate.symlink_to(root / "missing.json")
                    os.environ["OPENCODE_CONFIG_PATH"] = str(candidate)
                    with self.assertRaises(ConfigTransactionError):
                        edit_layered_config(lambda data: data.update({"changed": True}))
                    self.assertEqual(victim_before, victim.read_bytes())

    def test_timeout_validation_and_existing_lock_deadline(self) -> None:
        with self.isolated() as (root, _home, _project):
            config = root / "config.json"
            _write_config(config, {"value": 1})
            os.environ["OPENCODE_CONFIG_PATH"] = str(config)
            for timeout in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(timeout=timeout), self.assertRaises(
                    ConfigTransactionError
                ) as raised:
                    edit_layered_config(lambda _data: None, timeout_ms=timeout)
                self.assertEqual("config_invalid_timeout", raised.exception.reason_code)

            lock = _lock_registry() / _lock_name("namespace:layered-config")
            lock.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            token = lock / LOCK_OWNER_TOKEN
            token.write_bytes(b"a" * 64 + b"\n")
            token.chmod(PRIVATE_FILE_MODE)
            started = time.monotonic()
            with self.assertRaises(ConfigTransactionError) as raised:
                edit_layered_config(lambda _data: None, timeout_ms=60)
            elapsed = time.monotonic() - started
            self.assertEqual("config_lock_timeout", raised.exception.reason_code)
            self.assertGreaterEqual(elapsed, 0.04)
            self.assertLess(elapsed, 0.5)
            token.unlink()
            lock.rmdir()

    def test_batch_alias_composition_and_partial_commit_metadata(self) -> None:
        with self.isolated() as (root, _home, _project):
            first = root / "a.json"
            second = root / "b.json"
            alias = root / "alias.json"
            _write_config(first, {"count": 0})
            _write_config(second, {"value": 0})
            alias.symlink_to(first)

            result = edit_config_batch(
                (
                    ConfigFileParticipant(first, lambda data: data.update({"count": 1})),
                    ConfigFileParticipant(alias, lambda data: data.update({"extra": True})),
                )
            )
            self.assertTrue(result.committed)
            self.assertEqual(
                {"count": 1, "extra": True},
                json.loads(first.read_text(encoding="utf-8")),
            )
            self.assertTrue(alias.is_symlink())

            first_before = first.read_bytes()

            def inject(phase: str) -> None:
                if phase == f"after_replace:{first.resolve()}":
                    raise RuntimeError("partial")

            with self.assertRaises(ConfigTransactionError) as raised:
                edit_config_batch(
                    (
                        ConfigFileParticipant(first, lambda data: data.update({"count": 2})),
                        ConfigFileParticipant(second, lambda data: data.update({"value": 2})),
                    ),
                    _failure_injector=inject,
                )
            error = raised.exception
            self.assertEqual("partial_commit", error.reason_code)
            self.assertTrue(error.committed)
            self.assertTrue(error.lock_released)
            self.assertEqual([True, False], [item.committed for item in error.file_results])
            self.assertNotEqual(first_before, first.read_bytes())
            self.assertEqual(0, json.loads(second.read_text(encoding="utf-8"))["value"])

    def test_commit_and_release_failure_metadata(self) -> None:
        with self.isolated() as (root, _home, _project):
            config = root / "config.json"
            _write_config(config, {"value": 1})
            os.environ["OPENCODE_CONFIG_PATH"] = str(config)

            with self.assertRaises(ConfigTransactionError) as raised:
                edit_layered_config(
                    lambda data: data.update({"value": 2}),
                    _failure_injector=lambda phase: (
                        (_ for _ in ()).throw(RuntimeError("sync"))
                        if phase == "before_directory_sync"
                        else None
                    ),
                )
            self.assertEqual(
                "committed_durability_uncertain", raised.exception.reason_code
            )
            self.assertTrue(raised.exception.committed)
            self.assertTrue(raised.exception.lock_released)
            self.assertEqual(2, json.loads(config.read_text(encoding="utf-8"))["value"])

            injected = False

            def fail_release(phase: str) -> None:
                nonlocal injected
                if phase == "after_lock_remove" and not injected:
                    injected = True
                    raise RuntimeError("release sync")

            with self.assertRaises(ConfigTransactionError) as raised:
                edit_layered_config(
                    lambda data: data.update({"value": 3}),
                    _failure_injector=fail_release,
                )
            self.assertEqual(
                "committed_lock_release_failed", raised.exception.reason_code
            )
            self.assertTrue(raised.exception.committed)
            self.assertTrue(raised.exception.lock_released)


if __name__ == "__main__":
    unittest.main()
