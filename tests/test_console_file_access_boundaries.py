"""Exercise actual standalone modules with synthetic access tokens and temp files."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import sys

import pytest


@pytest.fixture(
    params=["norman_codex_web.py", "agent_console_template/agent_console_web.py"]
)
def console(request, monkeypatch, tmp_path):
    for prefix in ("NORMAN", "HOUSEBOT"):
        monkeypatch.setenv(f"{prefix}_CODEX_WEB_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv(f"{prefix}_CODEX_HOME", str(tmp_path / "codex"))
        monkeypatch.setenv(f"{prefix}_CODEX_WEB_TOKEN", "synthetic-access-only")
    path = Path(__file__).resolve().parents[1] / "scripts" / request.param
    name = "file_boundary_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def request_handler(console, path):
    handler = object.__new__(console.Handler)
    handler.path = path
    handler.headers = {"Content-Type": "application/json"}
    handler.wfile = io.BytesIO()
    handler.is_trusted_client = lambda: False
    handler.auth_cookie_token = lambda: ""
    handler.request_path_prefix = lambda: ""
    handler.should_redirect_canonical = lambda *args: False
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    return handler


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("token,expected", [("", 503), ("synthetic-access-only", 403)])
def test_untrusted_request_is_denied_before_file_or_attachment_access(
    console, monkeypatch, method, token, expected
):
    monkeypatch.setattr(console, "TOKEN", token)
    handler = request_handler(console, "/api/file?path=/synthetic/private")
    results = []
    handler.json_response = lambda payload, status: results.append((payload, status))
    handler.serve_file_target = lambda *args: pytest.fail("unauthorized file access")
    handler._read_request_body = lambda: b"{}"
    getattr(handler, f"do_{method}")()
    assert int(results[0][1]) == expected
    if not token:
        assert "Remote access is not configured" in results[0][0]["error"]


@pytest.mark.parametrize("trusted", [False, True])
def test_configured_access_preserves_operator_file_browsing(
    console, monkeypatch, trusted
):
    monkeypatch.setattr(console, "TOKEN", "" if trusted else "synthetic-access-only")
    handler = request_handler(console, "/api/file?path=/synthetic/log.txt")
    handler.is_trusted_client = lambda: trusted
    handler.auth_cookie_token = lambda: "" if trusted else "synthetic-access-only"
    paths = []
    handler.serve_file_target = lambda params: paths.append(params["path"][0])
    handler.do_GET()
    assert paths == ["/synthetic/log.txt"]


def test_unconfigured_login_explains_configuration_and_hides_unusable_form(
    console, monkeypatch
):
    monkeypatch.setattr(console, "TOKEN", "")
    handler = request_handler(console, "/")
    statuses = []
    handler.send_response = statuses.append
    handler.render_token_gate({})
    html = handler.wfile.getvalue().decode()
    assert statuses == [503]
    assert "Remote access is not configured" in html
    assert 'action="/" hidden' in html


@pytest.mark.parametrize(
    "name",
    [
        "../../outside.txt",
        "image.png/../../../outside.txt",
        "notes.txt",
        "report.unknown",
    ],
)
def test_attachment_storage_uses_unique_files_and_preserves_display_names(
    console, monkeypatch, tmp_path, name
):
    root = tmp_path / "attachments"
    monkeypatch.setattr(console, "ATTACHMENTS_DIR", root)
    monkeypatch.setattr(console, "load_draft_attachments", lambda: [])
    monkeypatch.setattr(console, "save_draft_attachments", lambda entries: entries)
    first = console.create_draft_attachment(
        raw_bytes=b"first", name=name, content_type="text/plain", source="paste"
    )
    second = console.create_draft_attachment(
        raw_bytes=b"second", name=name, content_type="text/plain", source="paste"
    )
    assert first["name"] == second["name"] == name
    paths = [Path(entry["path"]) for entry in (first, second)]
    assert paths[0] != paths[1]
    assert all(path.parent == root for path in paths)
    assert all(path.suffix == ".txt" for path in paths)
    assert [path.read_bytes() for path in paths] == [b"first", b"second"]
    assert not (tmp_path / "outside.txt").exists()
