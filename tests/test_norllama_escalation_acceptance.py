from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _load_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "verify_escalation_rollout.py"
    )
    spec = importlib.util.spec_from_file_location(
        "verify_escalation_rollout_test",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AcceptanceHandler(BaseHTTPRequestHandler):
    model = "future-local:40b"

    def _send(self, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self._send({"ok": True})
        elif self.path == "/readyz":
            self._send(
                {
                    "ready": True,
                    "policy": {
                        "policy_id": "future-policy:abc123",
                        "lifecycle_state": "valid",
                    },
                }
            )
        elif self.path == "/v1/models":
            self._send({"data": [{"id": self.model}]})
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/chat/completions":
            self._send(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "NORMAN_RESIDENT_ACCEPTANCE_OK",
                            }
                        }
                    ]
                }
            )
            return
        if self.path != "/v1/escalation/shadow":
            self.send_error(404)
            return
        requested = payload.get("requested_role")
        prior = payload.get("prior_roles") or []
        approval = bool(payload.get("side_effects"))
        if requested == "frontier" and "authority" in prior:
            role = "frontier"
        elif requested == "frontier" or approval or payload.get("complexity") == "high":
            role = "authority"
        elif payload.get("complexity") == "moderate":
            role = "economy"
        else:
            role = "resident"
        self._send(
            {
                "mode": "shadow_only",
                "execution_authority_changed": False,
                "proposed_role": role,
                "proposed_model": {
                    "resident": self.model,
                    "economy": "future-cloud-fast",
                    "authority": "future-cloud-authority",
                    "frontier": "future-cloud-frontier",
                }[role],
                "approval_required": approval,
                "registry_version": "future-eval-winner",
                "frontier_gate": {
                    "passed": role == "frontier",
                },
            }
        )

    def log_message(self, _format, *_args):
        return


def test_acceptance_harness_discovers_models_from_live_policy() -> None:
    module = _load_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), AcceptanceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        receipt = module.run_acceptance(
            base_url=f"http://127.0.0.1:{server.server_port}",
            timeout_seconds=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert receipt["status"] == "passed"
    assert receipt["registry_version"] == "future-eval-winner"
    assert receipt["roles"]["resident"] == "future-local:40b"
    assert all(check["status"] == "passed" for check in receipt["checks"])
