from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import completion_gates


class CompletionGateEvidenceTest(unittest.TestCase):
    def create_repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "completion@example.invalid"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Completion Test"],
            cwd=repo,
            check=True,
        )
        (repo / ".gitignore").write_text(".opencode/*\n", encoding="utf-8")
        (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", ".gitignore", "tracked.txt"], cwd=repo, check=True
        )
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
        return repo

    def node_eval(self, source: str, *arguments: str) -> dict:
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", source, *arguments],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_node_written_evidence_is_validated_by_python_for_exact_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.create_repo(Path(tmp))
            module_url = (
                REPO_ROOT
                / "plugin/gateway-core/dist/hooks/validation-evidence-ledger/evidence.js"
            ).as_uri()
            result = self.node_eval(
                "import { markValidationEvidence } from "
                + json.dumps(module_url)
                + "; console.log(JSON.stringify(markValidationEvidence('cross-runtime', ['test'], process.argv[1])))",
                str(repo),
            )
            self.assertTrue(result["test"])
            snapshot = completion_gates.load_validation_snapshot(repo)
            self.assertTrue(snapshot["test"])

            (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
            self.assertEqual({}, completion_gates.load_validation_snapshot(repo))
            (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
            self.assertTrue(completion_gates.load_validation_snapshot(repo)["test"])

    def test_node_and_python_fingerprints_share_canonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.create_repo(Path(tmp))
            (repo / "untracked.txt").write_text("payload\n", encoding="utf-8")
            os.chmod(repo / "untracked.txt", 0o755)
            module_url = (
                REPO_ROOT
                / "plugin/gateway-core/dist/hooks/validation-evidence-ledger/evidence.js"
            ).as_uri()
            node_value = self.node_eval(
                "import { captureGitStateFingerprint } from "
                + json.dumps(module_url)
                + "; console.log(JSON.stringify(captureGitStateFingerprint(process.argv[1])))",
                str(repo),
            )
            self.assertEqual(node_value, completion_gates.git_state_fingerprint(repo))

    def test_python_rejects_permissive_or_legacy_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.create_repo(Path(tmp))
            runtime = repo / ".opencode" / "runtime"
            runtime.mkdir(parents=True, mode=0o700)
            runtime.chmod(0o700)
            path = runtime / "validation-evidence.json"
            path.write_text(
                json.dumps({"sessions": {}, "worktrees": {str(repo): {"test": True}}}),
                encoding="utf-8",
            )
            path.chmod(0o600)
            self.assertEqual({}, completion_gates.load_validation_snapshot(repo))

            fingerprint = completion_gates.git_state_fingerprint(repo)
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "worktrees": {
                            fingerprint["root"]: {
                                "fingerprint": fingerprint,
                                "evidence": {
                                    "lint": False,
                                    "test": True,
                                    "typecheck": False,
                                    "build": False,
                                    "security": False,
                                    "updatedAt": "2026-07-27T00:00:00Z",
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o644)
            self.assertEqual({}, completion_gates.load_validation_snapshot(repo))


if __name__ == "__main__":
    unittest.main()
