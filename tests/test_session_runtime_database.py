from __future__ import annotations

import importlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class RuntimeDatabaseConnectionTest(unittest.TestCase):
    def _module(self):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        return importlib.reload(importlib.import_module("session_command"))

    def test_runtime_diagnostic_connection_uses_readonly_uri(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode #?.db"
            sqlite3.connect(db_path).close()
            with patch.object(module.sqlite3, "connect", wraps=sqlite3.connect) as connect:
                connection = module._connect_runtime_database_readonly(db_path)
                connection.close()

            self.assertTrue(connect.call_args.kwargs["uri"])
            self.assertTrue(connect.call_args.args[0].endswith("?mode=ro"))

    def test_runtime_diagnostic_connection_does_not_create_missing_database(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            with self.assertRaises(sqlite3.OperationalError):
                module._connect_runtime_database_readonly(db_path)
            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
