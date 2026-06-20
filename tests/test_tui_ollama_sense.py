import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tui_ollama_sense.py"


def load_module():
    spec = importlib.util.spec_from_file_location("tui_ollama_sense", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TuiOllamaSenseTests(unittest.TestCase):
    def test_probe_endpoint_marks_preferred_model_usable(self):
        module = load_module()

        def fake_urlopen(req, timeout):
            self.assertEqual(req.full_url, "http://lan-host:11434/api/tags")
            self.assertEqual(timeout, 0.5)
            return DummyResponse({"models": [{"name": "qwen3:8b"}]})

        with mock.patch.object(module, "urlopen", fake_urlopen):
            result = module.probe_endpoint(
                "lan-host:11434", timeout=0.5, preferred_model="qwen3:8b"
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.usable)
        self.assertEqual(result.scope, "lan")
        self.assertEqual(result.models, ["qwen3:8b"])

    def test_build_report_marks_model_missing_not_degradation_ready(self):
        module = load_module()

        def fake_urlopen(req, timeout):
            return DummyResponse({"models": [{"name": "llama3.2:3b"}]})

        with mock.patch.object(module, "urlopen", fake_urlopen):
            report = module.build_report(
                ["http://127.0.0.1:11434"],
                timeout=0.5,
                preferred_model="qwen3:8b",
            )

        self.assertEqual(report["summary"]["online_endpoints"], 1)
        self.assertEqual(report["summary"]["usable_endpoints"], 0)
        self.assertFalse(report["summary"]["degradation_ready"])
        self.assertEqual(report["endpoints"][0]["status"], "model-missing")

    def test_configured_endpoints_adds_env_and_cli_allowlist(self):
        module = load_module()
        with mock.patch.dict(
            module.os.environ,
            {"NORMAN_TUI_OLLAMA_ENDPOINTS": "http://sal:11434, norman:11434"},
        ):
            endpoints = module.configured_endpoints(
                ["http://sal:11434"], autosense_lan=False
            )

        self.assertIn("http://127.0.0.1:11434", endpoints)
        self.assertIn("http://sal:11434", endpoints)
        self.assertIn("http://norman:11434", endpoints)
        self.assertEqual(endpoints.count("http://sal:11434"), 1)

    def test_configured_endpoints_autosenses_lan_candidates(self):
        module = load_module()
        with (
            mock.patch.object(
                module,
                "_hostname_candidates",
                return_value=["toy-box", "toy-box.home.arpa"],
            ),
            mock.patch.object(
                module, "_local_ipv4_candidates", return_value=["192.168.2.9"]
            ),
            mock.patch.object(
                module,
                "_arp_ipv4_candidates",
                return_value=["192.168.2.50", "169.254.1.10"],
            ),
            mock.patch.dict(
                module.os.environ, {"NORMAN_TUI_OLLAMA_LAN_CANDIDATE_LIMIT": "8"}
            ),
        ):
            endpoints = module.configured_endpoints(
                extra_lan_hosts=["work-special.home.arpa"],
                autosense_lan=True,
            )

        self.assertIn("http://work-special.home.arpa:11434", endpoints)
        self.assertIn("http://toy-box:11434", endpoints)
        self.assertIn("http://toy-box.home.arpa:11434", endpoints)
        self.assertIn("http://192.168.2.9:11434", endpoints)
        self.assertIn("http://192.168.2.50:11434", endpoints)
        self.assertNotIn("http://169.254.1.10:11434", endpoints)

    def test_build_report_counts_lan_endpoints(self):
        module = load_module()

        def fake_urlopen(req, timeout):
            if "192.168.2.50" in req.full_url:
                return DummyResponse({"models": [{"name": "qwen3:8b"}]})
            raise OSError("offline")

        with mock.patch.object(module, "urlopen", fake_urlopen):
            report = module.build_report(
                ["http://127.0.0.1:11434", "http://192.168.2.50:11434"],
                timeout=0.5,
                preferred_model="qwen3:8b",
            )

        self.assertEqual(report["summary"]["local_endpoints"], 1)
        self.assertEqual(report["summary"]["lan_endpoints"], 1)
        self.assertEqual(report["summary"]["online_lan_endpoints"], 1)
        self.assertEqual(
            report["summary"]["best_endpoint"], "http://192.168.2.50:11434"
        )


if __name__ == "__main__":
    unittest.main()
