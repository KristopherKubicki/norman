import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tui_vllm_sense.py"


def load_module():
    spec = importlib.util.spec_from_file_location("tui_vllm_sense", SCRIPT_PATH)
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
        if isinstance(self.payload, bytes):
            return self.payload
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


class TuiVllmSenseTests(unittest.TestCase):
    def test_probe_endpoint_reads_openai_models(self):
        module = load_module()

        def fake_urlopen(req, timeout, context=None):
            self.assertEqual(req.full_url, "http://spark:8000/v1/models")
            self.assertEqual(timeout, 0.5)
            self.assertIsNotNone(context)
            return DummyResponse({"data": [{"id": "Qwen/Qwen3-Coder-30B-A3B"}]})

        with mock.patch.object(module, "urlopen", fake_urlopen):
            result = module.probe_endpoint(
                "spark:8000",
                timeout=0.5,
                preferred_model="Qwen/Qwen3-Coder-30B-A3B",
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.usable)
        self.assertEqual(result.scope, "lan")
        self.assertEqual(result.models, ["Qwen/Qwen3-Coder-30B-A3B"])
        self.assertEqual(result.as_dict()["provider"], "vllm-openai-compatible")

    def test_configured_endpoints_autosenses_lan_hosts_and_ports(self):
        module = load_module()
        with (
            mock.patch.object(module, "_hostname_candidates", return_value=["spark"]),
            mock.patch.object(module, "_local_ipv4_candidates", return_value=[]),
            mock.patch.object(
                module,
                "_arp_ipv4_candidates",
                return_value=["192.168.2.50", "169.254.1.10"],
            ),
            mock.patch.dict(
                module.os.environ,
                {
                    "NORMAN_TUI_VLLM_DEFAULT_ENDPOINTS": "http://llm.home.arpa",
                    "NORMAN_TUI_VLLM_LAN_CANDIDATE_LIMIT": "8",
                    "NORMAN_TUI_VLLM_PORTS": "8001",
                },
            ),
        ):
            endpoints = module.configured_endpoints(
                extra_lan_hosts=["spark-1.home.arpa"],
                extra_ports=[8080],
                autosense_lan=True,
            )

        self.assertIn("http://llm.home.arpa", endpoints)
        self.assertIn("http://spark-1.home.arpa:8000", endpoints)
        self.assertIn("http://spark-1.home.arpa:8001", endpoints)
        self.assertIn("http://spark-1.home.arpa:8080", endpoints)
        self.assertIn("http://spark:8000", endpoints)
        self.assertIn("http://192.168.2.50:8000", endpoints)
        self.assertNotIn("http://169.254.1.10:8000", endpoints)

    def test_build_report_marks_model_missing(self):
        module = load_module()

        def fake_urlopen(req, timeout, context=None):
            return DummyResponse({"data": [{"id": "meta-llama/Llama-3.1-8B"}]})

        with mock.patch.object(module, "urlopen", fake_urlopen):
            report = module.build_report(
                ["http://spark:8000"],
                timeout=0.5,
                preferred_model="Qwen/Qwen3-Coder-30B-A3B",
            )

        self.assertEqual(report["summary"]["online_endpoints"], 1)
        self.assertEqual(report["summary"]["usable_endpoints"], 0)
        self.assertEqual(report["endpoints"][0]["status"], "model-missing")

    def test_probe_endpoint_marks_health_online_without_models_ready(self):
        module = load_module()
        requested_urls = []

        def fake_urlopen(req, timeout, context=None):
            requested_urls.append(req.full_url)
            if req.full_url.endswith("/v1/models"):
                return DummyResponse("not json yet")
            if req.full_url.endswith("/health"):
                return DummyResponse("ok")
            raise AssertionError(req.full_url)

        with mock.patch.object(module, "urlopen", fake_urlopen):
            report = module.build_report(["http://spark:8000"], timeout=0.5)

        self.assertEqual(
            requested_urls,
            ["http://spark:8000/v1/models", "http://spark:8000/health"],
        )
        self.assertEqual(report["summary"]["reachable_endpoints"], 1)
        self.assertEqual(report["summary"]["online_endpoints"], 0)
        self.assertEqual(report["summary"]["usable_endpoints"], 0)
        self.assertFalse(report["summary"]["degradation_ready"])
        self.assertEqual(
            report["endpoints"][0]["status"], "health-online-models-unavailable"
        )
        self.assertTrue(report["endpoints"][0]["health_ok"])

    def test_probe_endpoint_does_not_treat_plain_health_as_vllm(self):
        module = load_module()

        def fake_urlopen(req, timeout, context=None):
            if req.full_url.endswith("/v1/models"):
                raise module.error.HTTPError(
                    req.full_url, 404, "Not Found", hdrs=None, fp=None
                )
            raise AssertionError(req.full_url)

        with mock.patch.object(module, "urlopen", fake_urlopen):
            report = module.build_report(["http://norman:8000"], timeout=0.5)

        self.assertEqual(report["summary"]["reachable_endpoints"], 0)
        self.assertEqual(report["summary"]["online_endpoints"], 0)
        self.assertEqual(report["endpoints"][0]["status"], "not-openai-compatible")

    def test_probe_endpoint_adds_configured_bearer_token(self):
        module = load_module()

        def fake_urlopen(req, timeout, context=None):
            self.assertEqual(req.headers["Authorization"], "Bearer local-secret")
            return DummyResponse({"data": [{"id": "Qwen/Qwen3-Coder-30B-A3B"}]})

        with (
            mock.patch.object(module, "urlopen", fake_urlopen),
            mock.patch.dict(
                module.os.environ, {"NORMAN_TUI_VLLM_API_KEY": "local-secret"}
            ),
        ):
            result = module.probe_endpoint("spark:8000", timeout=0.5)

        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
