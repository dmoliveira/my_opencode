from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class KvforgeConnectNativeProviderTest(unittest.TestCase):
    def test_load_states_ignores_invalid_current_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            (home / ".kvforge").mkdir(parents=True, exist_ok=True)
            (home / ".kvforge" / "server.json").write_text("{invalid", encoding="utf-8")

            old_home = os.environ.get("HOME")
            try:
                os.environ["HOME"] = str(home)
                if str(SCRIPTS_DIR) not in sys.path:
                    sys.path.insert(0, str(SCRIPTS_DIR))

                sys.modules.pop("kvforge_discovery", None)
                kvforge_discovery = importlib.import_module("kvforge_discovery")
                kvforge_discovery = importlib.reload(kvforge_discovery)

                self.assertEqual([], kvforge_discovery.load_states())
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_connect_payload_writes_native_kvforge_provider_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            config_path = root / "opencode.json"
            gateway_config_path = root / "gateway-core.config.json"
            (home / ".kvforge").mkdir(parents=True, exist_ok=True)

            state = {
                "connection_name": "kvforge-gpt-5-4-mini",
                "provider_model": "openai/gpt-5.4-mini",
                "served_model_name": "gpt-5.4-mini",
                "base_url": "http://127.0.0.1:8010/v1",
                "pid": os.getpid(),
            }
            (home / ".kvforge" / "server.json").write_text(json.dumps(state), encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "$schema": "https://opencode.ai/config.json"
                    }
                ),
                encoding="utf-8",
            )
            gateway_config_path.write_text(
                json.dumps(
                    {
                        "llmDecisionRuntime": {
                            "env": {
                                "OPENAI_BASE_URL": "http://stale.invalid/v1",
                                "OPENAI_API_KEY": "stale",
                                "KEEP_ME": "1",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            old_home = os.environ.get("HOME")
            old_config_path = os.environ.get("OPENCODE_CONFIG_PATH")
            old_gateway_config_path = os.environ.get("MY_OPENCODE_GATEWAY_CONFIG_PATH")
            try:
                os.environ["HOME"] = str(home)
                os.environ["OPENCODE_CONFIG_PATH"] = str(config_path)
                os.environ["MY_OPENCODE_GATEWAY_CONFIG_PATH"] = str(gateway_config_path)
                if str(SCRIPTS_DIR) not in sys.path:
                    sys.path.insert(0, str(SCRIPTS_DIR))

                sys.modules.pop("kvforge_discovery", None)
                sys.modules.pop("connect_command", None)
                connect_command = importlib.import_module("connect_command")
                connect_command = importlib.reload(connect_command)

                live_models_payload = json.dumps(
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": "gpt-5.4-mini",
                                "max_model_len": 40960,
                            }
                        ],
                    }
                ).encode("utf-8")

                class _FakeResponse:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                    def read(self) -> bytes:
                        return live_models_payload

                import kvforge_discovery

                with mock.patch.object(
                    kvforge_discovery.urllib.request,
                    "urlopen",
                    return_value=_FakeResponse(),
                ):
                    payload = connect_command.connect_payload(["--model", "kvforge/gpt-5.4-mini"])
                written = json.loads(config_path.read_text(encoding="utf-8"))
                gateway_written = json.loads(gateway_config_path.read_text(encoding="utf-8"))

                self.assertEqual("PASS", payload["result"])
                self.assertEqual("kvforge/gpt-5.4-mini", payload["model"])
                self.assertEqual("openai/gpt-5.4-mini", payload["provider_model"])
                self.assertEqual("gpt-5.4-mini", payload["served_model_name"])
                self.assertEqual("kvforge/gpt-5.4-mini", written["model"])
                self.assertNotIn("llmDecisionRuntime", written)
                self.assertNotIn("kvforge", written)
                self.assertEqual(str(gateway_config_path), payload["gateway_write_path"])
                self.assertEqual("kvforge/gpt-5.4-mini", gateway_written["llmDecisionRuntime"]["model"])
                self.assertEqual({"KEEP_ME": "1"}, gateway_written["llmDecisionRuntime"]["env"])
                self.assertEqual(
                    {
                        "name": "KVForge",
                        "npm": "@ai-sdk/openai-compatible",
                        "options": {
                            "baseURL": "http://127.0.0.1:8010/v1",
                            "apiKey": "dummy",
                        },
                        "models": {
                            "gpt-5.4-mini": {
                                "name": "gpt-5.4-mini",
                                "limit": {
                                    "context": 40960,
                                    "output": 39936,
                                },
                            }
                        },
                    },
                    written["provider"]["kvforge"],
                )
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_config_path is None:
                    os.environ.pop("OPENCODE_CONFIG_PATH", None)
                else:
                    os.environ["OPENCODE_CONFIG_PATH"] = old_config_path
                if old_gateway_config_path is None:
                    os.environ.pop("MY_OPENCODE_GATEWAY_CONFIG_PATH", None)
                else:
                    os.environ["MY_OPENCODE_GATEWAY_CONFIG_PATH"] = old_gateway_config_path


if __name__ == "__main__":
    unittest.main()
