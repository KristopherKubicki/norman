"""Exercise the deployed Caddy version against a disposable loopback backend."""

import concurrent.futures
import contextlib
import http.server
import http.client
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from render_norman_bot_proxy_caddy import _gateway_proxy_lines
from render_norman_frontdoor_caddy import render_frontdoor_snippet


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def proxy(tmp_path):
    binary = shutil.which("caddy")
    if not binary:
        pytest.skip("Caddy integration test requires the caddy executable")
    frontend, backend = _port(), _port()
    # Shorten only the timeout for the outage test; retain production semantics.
    handlers = "\n".join(_gateway_proxy_lines("compere"))
    handlers = handlers.replace(":8000", f":{backend}").replace("120s", "2s")
    config = tmp_path / "Caddyfile"
    config.write_text(
        "{\n admin off\n auto_https off\n}\n"
        f"http://127.0.0.1:{frontend} {{\n{handlers}\n}}\n"
    )
    with (tmp_path / "caddy.log").open("w+") as log:
        process = subprocess.Popen(
            [binary, "run", "--config", str(config), "--adapter", "caddyfile"],
            stdout=log,
            stderr=log,
            env={
                **os.environ,
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_CONFIG_HOME": str(tmp_path / "config"),
            },
        )
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", frontend), timeout=0.1):
                        break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        pytest.fail(log.read())
                    time.sleep(0.02)
            yield f"http://127.0.0.1:{frontend}", backend
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@contextlib.contextmanager
def _backend(port, *, drop=False):
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get("Transfer-Encoding") == "chunked":
                body = b""
                while size := int(self.rfile.readline().strip(), 16):
                    body += self.rfile.read(size)
                    self.rfile.read(2)
                self.rfile.read(2)
            else:
                body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append(body)
            if drop:
                self.close_connection = True
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            time.sleep(0.1)
            self.wfile.write(b"data: done\n\n")

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(url, body):
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@pytest.mark.parametrize("path", ["/v1/responses", "/v1/responses/compact"])
def test_post_waits_for_backend_and_preserves_body_once(proxy, path):
    url, port = proxy
    body = b'{"input":"' + b"x" * 350_000 + b'"}'
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_post, url + path, body)
        time.sleep(0.4)
        with _backend(port) as received:
            status, response = pending.result(timeout=6)
            assert status == 200
            assert response == b"data: first\n\ndata: done\n\n"
            assert received == [body]


def test_accepted_post_is_not_replayed_after_disconnect(proxy):
    url, port = proxy
    with _backend(port, drop=True) as received:
        assert _post(url + "/v1/responses", b"test")[0] == 502
        assert received == [b"test"]


def test_down_backend_has_bounded_wait(proxy):
    url, _port_number = proxy
    start = time.monotonic()
    assert _post(url + "/v1/responses", b"test")[0] == 502
    assert 1.5 <= time.monotonic() - start < 5


def test_large_body_keeps_existing_unbuffered_delivery(proxy):
    url, port = proxy
    with _backend(port) as received:
        body = b"x" * 10_000_000
        assert _post(url + "/v1/responses", body)[0] == 200
        assert received == [body]


def test_all_inference_handlers_preserve_safe_retry_policy():
    for config in [
        "\n".join(_gateway_proxy_lines("compere")),
        render_frontdoor_snippet(),
    ]:
        for path in ["/v1/responses", "/v1/*"]:
            handler = config.split(f"handle {path} {{", 1)[1].split("header_up", 1)[0]
            assert "buffer_requests" in handler
            assert "^[0-9]{1,7}$" in handler
            assert "lb_try_duration 120s" in handler
            assert "lb_try_interval 250ms" in handler
            assert "lb_retry_match method GET" in handler


def test_unknown_length_body_keeps_existing_delivery(proxy):
    url, port = proxy
    # Chunked uploads have no Content-Length and must bypass retry buffering.
    with _backend(port) as received:
        connection = http.client.HTTPConnection(url.removeprefix("http://"), timeout=6)
        try:
            connection.request(
                "POST", "/v1/responses", body=iter([b"test"]), encode_chunked=True
            )
            assert connection.getresponse().status == 200
            assert received == [b"test"]
        finally:
            connection.close()
