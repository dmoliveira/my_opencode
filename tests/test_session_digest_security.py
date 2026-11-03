from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class SessionDigestSecurityTest(unittest.TestCase):
    def _module(self, digest_path: Path, index_path: Path):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        env = {
            "MY_OPENCODE_DIGEST_PATH": str(digest_path),
            "MY_OPENCODE_SESSION_INDEX_PATH": str(index_path),
            "OPENCODE_SESSION_ID": "digest-security-session",
            "CI": "true",
        }
        with patch.dict(os.environ, env):
            importlib.reload(importlib.import_module("session_metadata_index"))
            module = importlib.reload(importlib.import_module("session_digest"))
        return module, env

    def _run(self, module, env: dict[str, str], args: list[str]) -> tuple[int, str]:
        with patch.dict(os.environ, env), contextlib.redirect_stdout(
            io.StringIO()
        ) as output:
            code = module.command_run(args)
        return code, output.getvalue()

    def test_two_atomic_generations_create_private_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path = root / "private" / "digests" / "last-session.json"
            index_path = root / "private" / "sessions" / "index.json"
            module, env = self._module(digest_path, index_path)

            code, output = self._run(
                module,
                env,
                ["--reason", "manual", "--path", str(digest_path)],
            )
            self.assertEqual(0, code, output)
            self.assertIn("digest_initial_durability: synced", output)
            self.assertIn("digest_final_durability: synced", output)
            self.assertEqual(0o600, digest_path.stat().st_mode & 0o777)
            self.assertEqual(0o600, index_path.stat().st_mode & 0o777)
            self.assertEqual(0o600, module._digest_lock_path(digest_path).stat().st_mode & 0o777)
            self.assertEqual(0o600, module._index_lock_path().stat().st_mode & 0o777)
            self.assertEqual(0o700, digest_path.parent.stat().st_mode & 0o777)
            self.assertEqual(0o700, index_path.parent.stat().st_mode & 0o777)
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            self.assertEqual("PASS", digest["session_index"]["result"])

    def test_alias_preflight_precedes_post_session_and_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / "shared.json"
            module, env = self._module(shared, shared)
            with patch.object(module, "run_post_session") as post_hook, patch.object(
                module,
                "build_digest",
            ) as build_digest:
                code, output = self._run(
                    module,
                    env,
                    ["--run-post", "--path", str(shared)],
                )
            self.assertEqual(1, code)
            self.assertIn("reason_code: session_sidecar_alias", output)
            post_hook.assert_not_called()
            build_digest.assert_not_called()
            self.assertFalse(shared.exists())
            self.assertFalse(module._digest_lock_path(shared).exists())

    def test_post_session_mode_widening_is_observed_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path = root / "digest.json"
            index_path = root / "index.json"
            original = b'{"previous": true}'
            digest_path.write_bytes(original)
            digest_path.chmod(0o600)
            module, env = self._module(digest_path, index_path)

            def widen(*_args, **_kwargs):
                digest_path.chmod(0o644)
                return {"attempted": True, "exit_code": 0, "timed_out": False}

            with patch.object(module, "load_post_session_config", return_value={}), patch.object(
                module,
                "run_post_session",
                side_effect=widen,
            ):
                code, output = self._run(
                    module,
                    env,
                    ["--run-post", "--path", str(digest_path)],
                )
            self.assertEqual(1, code)
            self.assertIn("session_sidecar_insecure_permissions", output)
            self.assertEqual(original, digest_path.read_bytes())
            self.assertEqual(0o644, digest_path.stat().st_mode & 0o777)
            self.assertFalse(index_path.exists())
            self.assertFalse(module._digest_lock_path(digest_path).exists())

    def test_post_session_content_change_is_preserved_before_publication(self) -> None:
        for initially_exists in (False, True):
            with self.subTest(initially_exists=initially_exists), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                digest_path = root / "digest.json"
                index_path = root / "index.json"
                if initially_exists:
                    digest_path.write_bytes(b'{"generation": 1}')
                    digest_path.chmod(0o600)
                hook_bytes = b'{"generation": 2, "secret": "synthetic-hook-canary"}'
                module, env = self._module(digest_path, index_path)

                def modify(*_args, _path=digest_path, _hook_bytes=hook_bytes, **_kwargs):
                    _path.write_bytes(_hook_bytes)
                    _path.chmod(0o600)
                    return {"attempted": True, "exit_code": 0, "timed_out": False}

                with (
                    patch.object(module, "build_digest", return_value={}),
                    patch.object(module, "load_post_session_config", return_value={}),
                    patch.object(module, "run_post_session", side_effect=modify),
                    patch.object(module, "update_session_index") as update_index,
                ):
                    code, output = self._run(module, env, ["--run-post", "--path", str(digest_path)])
                self.assertEqual(1, code, output)
                self.assertIn("reason_code: session_sidecar_snapshot_changed", output)
                self.assertIn("digest_committed: no", output)
                self.assertNotIn("synthetic-hook-canary", output)
                self.assertEqual(hook_bytes, digest_path.read_bytes())
                update_index.assert_not_called()
                self.assertFalse(index_path.exists())

    def test_unparseable_existing_digest_is_preserved_before_hooks_or_publication(self) -> None:
        cases = (
            (b"{synthetic-malformed-canary", "session_sidecar_malformed_json"),
            (b"\xffsynthetic-utf8-canary", "session_sidecar_invalid_utf8"),
            (b'["synthetic-root-canary"]', "session_sidecar_invalid_root"),
        )
        for original, reason in cases:
            for run_post in (False, True):
                with self.subTest(reason=reason, run_post=run_post), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    digest_path, index_path = root / "digest.json", root / "index.json"
                    digest_path.write_bytes(original)
                    digest_path.chmod(0o600)
                    inode = digest_path.stat().st_ino
                    module, env = self._module(digest_path, index_path)
                    args = ["--path", str(digest_path)] + (["--run-post"] if run_post else [])
                    with (
                        patch.object(module, "build_digest", return_value={}) as build_digest,
                        patch.object(module, "run_post_session") as post_hook,
                        patch.object(module, "update_session_index") as update_index,
                    ):
                        code, output = self._run(module, env, args)
                    self.assertEqual(1, code, output)
                    self.assertIn(f"reason_code: {reason}", output)
                    self.assertIn("digest_committed: no", output)
                    self.assertNotIn("canary", output)
                    self.assertEqual(original, digest_path.read_bytes())
                    self.assertEqual(inode, digest_path.stat().st_ino)
                    build_digest.assert_not_called()
                    post_hook.assert_not_called()
                    update_index.assert_not_called()
                    self.assertFalse(index_path.exists())
                    self.assertFalse(module._digest_lock_path(digest_path).exists())

    def test_unchanged_post_session_allows_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path, index_path = root / "digest.json", root / "index.json"
            digest_path.write_bytes(b'{"generation": 1}')
            digest_path.chmod(0o600)
            module, env = self._module(digest_path, index_path)
            with (
                patch.object(module, "build_digest", return_value={}),
                patch.object(module, "load_post_session_config", return_value={}),
                patch.object(module, "run_post_session", return_value={"attempted": False}),
                patch.object(module, "update_session_index", return_value={"result": "PASS"}) as update_index,
            ):
                code, output = self._run(module, env, ["--run-post", "--path", str(digest_path)])
            self.assertEqual(0, code, output)
            self.assertEqual("PASS", json.loads(digest_path.read_bytes())["session_index"]["result"])
            update_index.assert_called_once()

    def test_change_between_hook_revalidation_and_lock_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path, index_path = root / "digest.json", root / "index.json"
            digest_path.write_bytes(b'{"generation": 1}')
            digest_path.chmod(0o600)
            replacement = b'{"generation": 2}'
            module, env = self._module(digest_path, index_path)
            real_lock = module.secure_sidecar_lock

            @contextlib.contextmanager
            def change_on_lock(*args, **kwargs):
                with real_lock(*args, **kwargs):
                    digest_path.write_bytes(replacement)
                    digest_path.chmod(0o600)
                    yield

            with (
                patch.object(module, "build_digest", return_value={}),
                patch.object(module, "load_post_session_config", return_value={}),
                patch.object(module, "run_post_session", return_value={"attempted": False}),
                patch.object(module, "secure_sidecar_lock", side_effect=change_on_lock),
                patch.object(module, "update_session_index") as update_index,
            ):
                code, output = self._run(module, env, ["--run-post", "--path", str(digest_path)])
            self.assertEqual(1, code, output)
            self.assertIn("reason_code: session_sidecar_snapshot_changed", output)
            self.assertIn("generation: initial", output)
            self.assertEqual(replacement, digest_path.read_bytes())
            update_index.assert_not_called()

    def test_change_while_building_without_hook_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path, index_path = root / "digest.json", root / "index.json"
            digest_path.write_bytes(b'{"generation": 1}')
            digest_path.chmod(0o600)
            replacement = b'{"generation": 2}'
            module, env = self._module(digest_path, index_path)

            def change_during_build(**_kwargs):
                digest_path.write_bytes(replacement)
                digest_path.chmod(0o600)
                return {}

            with (
                patch.object(module, "build_digest", side_effect=change_during_build),
                patch.object(module, "update_session_index") as update_index,
            ):
                code, output = self._run(module, env, ["--path", str(digest_path)])
            self.assertEqual(1, code, output)
            self.assertIn("reason_code: session_sidecar_snapshot_changed", output)
            self.assertEqual(replacement, digest_path.read_bytes())
            update_index.assert_not_called()

    def test_final_hook_malformed_replacement_fails_after_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path = root / "digest.json"
            index_path = root / "index.json"
            module, env = self._module(digest_path, index_path)

            def replace_with_malformed(_command: str, path: Path) -> int:
                path.write_bytes(b"{malformed-hook-canary")
                path.chmod(0o600)
                return 0

            with patch.object(module, "run_hook", side_effect=replace_with_malformed):
                code, output = self._run(
                    module,
                    env,
                    ["--hook", "ignored", "--path", str(digest_path)],
                )
            self.assertEqual(1, code)
            self.assertIn("reason_code: session_sidecar_malformed_json", output)
            self.assertIn("generation: post_hook", output)
            self.assertIn("digest_committed: yes", output)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(index["sessions"]))

    def test_final_hook_safe_replacement_controls_final_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path = root / "digest.json"
            index_path = root / "index.json"
            module, env = self._module(digest_path, index_path)

            def replace_with_failure(_command: str, path: Path) -> int:
                path.write_text(
                    json.dumps(
                        {
                            "timestamp": "2026-07-30T00:00:00Z",
                            "reason": "hook",
                            "cwd": str(root),
                            "git": {},
                            "session_index": {
                                "result": "FAIL",
                                "reason_code": "session_index_hook_replaced",
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                path.chmod(0o600)
                return 0

            with patch.object(module, "run_hook", side_effect=replace_with_failure):
                code, output = self._run(
                    module,
                    env,
                    ["--hook", "ignored", "--path", str(digest_path)],
                )
            self.assertEqual(1, code)
            self.assertIn("hook_digest_superseded: yes", output)
            self.assertIn("session_index_reason: session_index_hook_replaced", output)

    def test_final_hook_rejects_non_object_session_index(self) -> None:
        for invalid in ([], None, "invalid"):
            with self.subTest(value=invalid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                digest_path = root / "digest.json"
                index_path = root / "index.json"
                module, env = self._module(digest_path, index_path)

                def replace_invalid(_command: str, path: Path) -> int:
                    path.write_text(
                        json.dumps(
                            {
                                "timestamp": "2026-07-30T00:00:00Z",
                                "reason": "hook",
                                "cwd": str(root),
                                "git": {},
                                "session_index": invalid,
                            }
                        ),
                        encoding="utf-8",
                    )
                    path.chmod(0o600)
                    return 0

                with patch.object(module, "run_hook", side_effect=replace_invalid):
                    code, output = self._run(
                        module,
                        env,
                        ["--hook", "ignored", "--path", str(digest_path)],
                    )
                self.assertEqual(1, code)
                self.assertIn("hook_digest_superseded: yes", output)
                self.assertIn(
                    "reason_code: session_sidecar_malformed_json",
                    output,
                )

    def test_final_publication_failure_leaves_initial_digest_and_committed_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path = root / "digest.json"
            index_path = root / "index.json"
            module, env = self._module(digest_path, index_path)
            real_write = module.write_digest
            calls = 0

            def fail_final(path: Path, digest: dict, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise module.SidecarSecurityError(
                        "session_sidecar_write_error",
                        "injected final publication failure",
                        phase="publish",
                    )
                return real_write(path, digest, **kwargs)

            with patch.object(module, "write_digest", side_effect=fail_final):
                code, output = self._run(
                    module,
                    env,
                    ["--path", str(digest_path)],
                )
            self.assertEqual(1, code)
            self.assertIn("generation: final", output)
            self.assertIn("session_index_result: PASS", output)
            self.assertIn("digest_committed: yes", output)
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            self.assertNotIn("session_index", digest)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(index["sessions"]))

    def test_show_and_doctor_use_stable_secure_read_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest_path = root / "digest.json"
            index_path = root / "index.json"
            digest_path.write_bytes(b"{malformed")
            digest_path.chmod(0o600)
            module, env = self._module(digest_path, index_path)
            with patch.dict(os.environ, env), contextlib.redirect_stdout(
                io.StringIO()
            ) as output:
                show_code = module.command_show(["--path", str(digest_path)])
            self.assertEqual(1, show_code)
            self.assertIn("reason_code: session_sidecar_malformed_json", output.getvalue())

            report = module.collect_doctor(digest_path)
            self.assertEqual("FAIL", report["result"])
            self.assertEqual("session_sidecar_malformed_json", report["reason_code"])
            self.assertNotIn("malformed", " ".join(report["problems"]))


if __name__ == "__main__":
    unittest.main()
