"""Exercise standalone console boundaries without starting services or reading state."""

from __future__ import annotations

import ast
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import re
from types import SimpleNamespace
import urllib.parse
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONSOLES = (
    "scripts/norman_codex_web.py",
    "scripts/agent_console_template/agent_console_web.py",
)
GATEWAY = "scripts/norllama/norllama_gateway.py"


def load_definitions(path, names, namespace):
    """Compile actual boundary definitions without runtime startup side effects."""
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if getattr(node, "name", "") in names]
    assert {node.name for node in nodes} == set(names)
    for node in nodes:
        if node.name == "Handler":
            node.body = [
                item for item in node.body if getattr(item, "name", "") == "send_header"
            ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), namespace)
    return SimpleNamespace(**namespace)


@pytest.fixture(params=CONSOLES)
def console(request):
    return load_definitions(
        request.param,
        ["normalize_capture_url", "capture_web_attachment"],
        {"urlparse": urllib.parse.urlparse, "Any": object},
    )


@pytest.mark.parametrize(
    "url",
    [
        "--remote-debugging-port=9222",
        "file:///etc/passwd",
        "https://user:pass@host/",
        "https://host/\r\nX-Test: yes",
        "https://host/\x00",
        "https://host\\@evil/",
        "https://host:99999/",
        "https://:443/",
    ],
)
def test_capture_rejects_ambiguous_urls(console, url):
    with pytest.raises(ValueError):
        console.normalize_capture_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://hal.home.arpa:8080/",
        "https://[::1]/",
        "https://norman.home.arpa/?q=--flag",
    ],
)
def test_capture_preserves_internal_urls(console, url):
    assert console.normalize_capture_url(url) == url


def test_capture_url_is_a_single_positional_argument(console, tmp_path):
    import os
    import subprocess
    import tempfile

    calls = []

    def run(cmd, **kwargs):
        assert kwargs.get("shell", False) is False
        calls.append(cmd)
        output = next(
            arg.split("=", 1)[1] for arg in cmd if arg.startswith("--screenshot=")
        )
        Path(output).write_bytes(b"png")
        return SimpleNamespace(returncode=0)

    namespace = console.capture_web_attachment.__globals__
    namespace.update(
        screenshot_browser_binary=lambda: "/usr/bin/chromium",
        ensure_attachments_dir=lambda: None,
        ATTACHMENTS_DIR=tmp_path,
        SCREENSHOT_WINDOW_WIDTH=1280,
        SCREENSHOT_WINDOW_HEIGHT=720,
        SCREENSHOT_CAPTURE_TIMEOUT=10,
        tempfile=tempfile,
        Path=Path,
        os=os,
        subprocess=SimpleNamespace(
            run=run,
            DEVNULL=subprocess.DEVNULL,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
        create_draft_attachment=lambda **kwargs: kwargs,
    )
    url = "https://hal.home.arpa/?q=hello;$(id)&next=--no-sandbox"
    result = console.capture_web_attachment(url=url)
    assert calls[0][-2:] == ["--", url]
    assert result["url"] == url
    assert result["raw_bytes"] == b"png"


@pytest.mark.parametrize("path", (*CONSOLES, GATEWAY))
def test_response_headers_cannot_split_the_response(path):
    module = load_definitions(
        path,
        ["Handler", "safe_header_value", "safe_header_name"],
        {"BaseHTTPRequestHandler": BaseHTTPRequestHandler, "re": re},
    )
    handler = object.__new__(module.Handler)
    handler.request_version = "HTTP/1.1"
    handler.send_header("X-Upstream", "peer\r\nSet-Cookie: forged=1\n")
    assert handler._headers_buffer == [b"X-Upstream: peerSet-Cookie: forged=1\r\n"]
    with pytest.raises(ValueError):
        handler.send_header("X-Upstream\r\nSet-Cookie", "forged=1")
    assert len(handler._headers_buffer) == 1


@pytest.fixture
def gateway():
    return load_definitions(
        GATEWAY,
        ["same_origin_url", "SameOriginRedirectHandler", "fetch_url"],
        {"urllib": __import__("urllib"), "DEFAULT_TIMEOUT_S": 2, "USER_AGENT": "test"},
    )


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.invalid/status",
        "//evil.invalid/status",
        "http://peer.home.arpa/status",
        "https://peer.home.arpa:444/status",
        "https://user@peer.home.arpa/status",
        "https://peer.home.arpa.evil.invalid/status",
        "https://peer.home.arpa\\@evil.invalid/status",
        "/status\r\nX-Test: yes",
        "file:///etc/passwd",
    ],
)
def test_peer_status_cannot_change_service(gateway, target):
    with pytest.raises(ValueError):
        gateway.same_origin_url("https://peer.home.arpa/", target)


@pytest.mark.parametrize(
    "target",
    [
        "/v1/prefetch/status?job_id=123",
        "v1/prefetch/status?job_id=123",
        "https://peer.home.arpa/v1/prefetch/status?job_id=123",
        "https://peer.home.arpa:443/v1/prefetch/status?job_id=123",
    ],
)
def test_peer_status_preserves_same_service(gateway, target):
    assert (
        gateway.same_origin_url("https://peer.home.arpa/", target)
        == "https://peer.home.arpa/v1/prefetch/status?job_id=123"
    )


def test_redirects_enforce_origin_on_every_hop(gateway):
    handler = gateway.SameOriginRedirectHandler()
    request = urllib.request.Request("https://peer.home.arpa/start")
    same = handler.redirect_request(request, None, 302, "Found", {}, "/next")
    assert same.full_url == "https://peer.home.arpa/next"
    with pytest.raises(ValueError):
        handler.redirect_request(
            same, None, 302, "Found", {}, "https://evil.invalid/next"
        )


def test_fetch_blocks_cross_origin_redirect_before_contacting_target(gateway):
    """Use real HTTP redirects to verify that fetch_url installs the policy."""
    from contextlib import ExitStack
    from http.server import ThreadingHTTPServer
    import threading

    contacted = []

    class TestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            contacted.append(self.path)
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/same-origin")
            elif self.path == "/same-origin":
                self.send_response(302)
                self.send_header("Location", target)
            else:
                self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    with ExitStack() as stack:
        servers = [ThreadingHTTPServer(("127.0.0.1", 0), TestHandler) for _ in range(2)]
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            stack.callback(server.server_close)
            stack.callback(thread.join, 2)
            stack.callback(server.shutdown)
        target = f"http://127.0.0.1:{servers[1].server_port}/must-not-be-contacted"
        with pytest.raises(ValueError, match="configured service origin"):
            gateway.fetch_url(f"http://127.0.0.1:{servers[0].server_port}/start")
        assert contacted == ["/start", "/same-origin"]
