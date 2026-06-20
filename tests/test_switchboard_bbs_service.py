from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
from pathlib import Path


def _load_switchboard_bbs_service():
    script_path = (
        Path(__file__).resolve().parents[1] / "tmp" / "switchboard_bbs_service.py"
    )
    spec = importlib.util.spec_from_file_location(
        "switchboard_bbs_service", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeStore:
    def list_heartbeats(self):
        return {}


def test_blocked_thread_loop_state_is_not_picked_up() -> None:
    module = _load_switchboard_bbs_service()
    handler = object.__new__(module.SwitchboardHandler)
    handler.store = _FakeStore()

    loop = handler._thread_loop_state(
        {"owner": "subprime", "status": "blocked"},
        [
            {
                "posted_at": "2026-06-08T11:48:04Z",
                "posted_by": "subprime",
                "metadata": {"loop_state": "picked_up"},
            }
        ],
    )

    assert loop["state"] == "blocked"
    assert loop["label"] == "Blocked"


def test_artifact_path_stays_inside_artifact_dir(tmp_path: Path) -> None:
    module = _load_switchboard_bbs_service()
    handler = object.__new__(module.SwitchboardHandler)
    handler.artifact_dir = tmp_path.resolve()

    assert handler._artifact_path("bench.zip") == tmp_path / "bench.zip"

    for bad in ("../secret", "nested/bench.zip", "..", ""):
        try:
            handler._artifact_path(bad)
        except ValueError as exc:
            assert str(exc) == "invalid_artifact"
        else:
            raise AssertionError(f"accepted invalid artifact name: {bad}")


def test_write_artifact_from_payload_stores_downloadable_file(tmp_path: Path) -> None:
    module = _load_switchboard_bbs_service()
    handler = object.__new__(module.SwitchboardHandler)
    handler.artifact_dir = tmp_path.resolve()
    data = b"benchmark artifact contents\n"

    artifact = handler._write_artifact_from_payload(
        {
            "filename": "bench.md",
            "label": "Benchmark report",
            "content_base64": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )

    assert artifact["label"] == "Benchmark report"
    assert artifact["href"] == "/artifacts/bench.md"
    assert artifact["bytes"] == len(data)
    assert artifact["sha256"] == hashlib.sha256(data).hexdigest()
    assert (tmp_path / "bench.md").read_bytes() == data


def test_write_artifact_from_payload_rejects_bad_digest(tmp_path: Path) -> None:
    module = _load_switchboard_bbs_service()
    handler = object.__new__(module.SwitchboardHandler)
    handler.artifact_dir = tmp_path.resolve()

    try:
        handler._write_artifact_from_payload(
            {
                "filename": "bench.md",
                "content_text": "contents",
                "sha256": "0" * 64,
            }
        )
    except ValueError as exc:
        assert str(exc) == "artifact_sha256_mismatch"
    else:
        raise AssertionError("accepted an artifact with the wrong sha256")

    assert not (tmp_path / "bench.md").exists()


def test_capabilities_advertises_artifact_upload_endpoint() -> None:
    module = _load_switchboard_bbs_service()
    handler = object.__new__(module.SwitchboardHandler)

    endpoints = handler._capabilities()["endpoints"]

    assert endpoints["artifact"] == "GET /artifacts/{filename}"
    assert endpoints["upload_artifact"] == "POST /api/v1/artifacts"
