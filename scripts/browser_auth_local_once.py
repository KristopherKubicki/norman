#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #12171f;
      --panel: #1a202a;
      --border: #34404f;
      --text: #e6edf3;
      --muted: #9fb0c3;
      --ok: #6ed2a1;
      --warn: #d7b97a;
      --danger: #d18b99;
      --link: #87b6ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: var(--bg);
      color: var(--text);
      font: 16px/1.5 system-ui, sans-serif;
      padding: 24px;
    }}
    main {{
      width: min(760px, 100%);
      padding: 24px;
      border: 1px solid var(--border);
      background: var(--panel);
      border-radius: 14px;
      display: grid;
      gap: 12px;
    }}
    h1 {{
      margin: 0;
      font-size: 1.9rem;
      letter-spacing: -0.02em;
    }}
    p {{
      margin: 0;
      color: var(--muted);
    }}
    .badge {{
      display: inline-block;
      margin-bottom: 2px;
      padding: 4px 10px;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: {badge_color};
      justify-self: start;
    }}
    .mono {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
      font: 0.95em/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--text);
      word-break: break-all;
    }}
    .list {{
      display: grid;
      gap: 10px;
      margin-top: 4px;
    }}
    .card {{
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: rgba(255,255,255,0.02);
      display: grid;
      gap: 8px;
    }}
    .label {{
      font-size: 0.82rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    a {{ color: var(--link); }}
  </style>
</head>
<body>
  <main>
    <div class="badge">{badge}</div>
    <h1>{title}</h1>
    <p>{detail}</p>
    {extra}
  </main>
</body>
</html>
"""


def render_page(
    *,
    badge: str,
    badge_color: str,
    title: str,
    detail: str,
    extra: str = "",
) -> bytes:
    return HTML_TEMPLATE.format(
        badge=html.escape(badge),
        badge_color=badge_color,
        title=html.escape(title),
        detail=html.escape(detail),
        extra=extra,
    ).encode("utf-8")


def merge_forward_url_query(
    forward_url: str,
    query_items: dict[str, str],
) -> str:
    parsed = urlparse(forward_url)
    merged = parse_qsl(parsed.query, keep_blank_values=True)
    merged.extend((key, value) for key, value in query_items.items())
    return urlunparse(parsed._replace(query=urlencode(merged, doseq=True)))


def build_arm_href(
    *,
    state: str,
    forward_url: str,
    label: str = "",
    console_url: str = "",
    next_url: str = "",
) -> str:
    query_items = {
        "state": state,
        "forward_url": forward_url,
    }
    if label:
        query_items["label"] = label
    if console_url:
        query_items["console_url"] = console_url
    if next_url:
        query_items["next_url"] = next_url
    return "/arm?" + urlencode(query_items)


def build_return_to_console_extra(
    *,
    console_url: str,
    label: str = "",
) -> str:
    if not console_url:
        return ""
    escaped_console_url = html.escape(console_url)
    console_label = html.escape(label or "console")
    script = f"""
<script>
(() => {{
  const target = {json.dumps(console_url)};
  const attemptReturn = () => {{
    try {{
      window.close();
    }} catch (_err) {{
      // ignore close failures and fall back to redirect
    }}
    window.setTimeout(() => {{
      if (!target) {{
        return;
      }}
      try {{
        window.location.replace(target);
      }} catch (_err) {{
        window.location.href = target;
      }}
    }}, 320);
  }};
  window.setTimeout(attemptReturn, 900);
}})();
</script>
"""
    return (
        f"<p>This window will close automatically or return you to "
        f'<a href="{escaped_console_url}">{console_label}</a>.</p>' + script
    )


class RelayServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        default_forward_url: str = "",
        arm_ttl_seconds: int = 900,
    ) -> None:
        super().__init__(server_address, handler)
        self.default_forward_url = default_forward_url.rstrip("?")
        self.arm_ttl_seconds = max(60, arm_ttl_seconds)
        self.pending: dict[str, dict[str, Any]] = {}
        self.pending_lock = threading.Lock()
        self.completed = threading.Event()
        self.result: dict[str, Any] = {}

    def arm_target(
        self,
        *,
        state: str,
        forward_url: str,
        label: str = "",
        console_url: str = "",
    ) -> dict[str, Any]:
        record = {
            "state": state,
            "forward_url": forward_url.rstrip("?"),
            "label": label.strip(),
            "console_url": console_url.strip(),
            "armed_at": int(time.time()),
        }
        with self.pending_lock:
            self.prune_targets()
            self.pending[state] = record
        return dict(record)

    def pop_target(self, state: str) -> dict[str, Any] | None:
        with self.pending_lock:
            self.prune_targets()
            return self.pending.pop(state, None)

    def prune_targets(self) -> None:
        cutoff = time.time() - self.arm_ttl_seconds
        stale = [
            key
            for key, value in self.pending.items()
            if int(value.get("armed_at") or 0) < cutoff
        ]
        for key in stale:
            self.pending.pop(key, None)

    def status_payload(self) -> dict[str, Any]:
        with self.pending_lock:
            self.prune_targets()
            items = [
                {
                    "state": key,
                    "forward_url": value.get("forward_url", ""),
                    "label": value.get("label", ""),
                    "console_url": value.get("console_url", ""),
                    "armed_at": value.get("armed_at", 0),
                }
                for key, value in sorted(
                    self.pending.items(),
                    key=lambda item: int(item[1].get("armed_at") or 0),
                    reverse=True,
                )
            ]
        return {
            "ok": True,
            "default_forward_url": self.default_forward_url,
            "pending_count": len(items),
            "pending": items,
            "last_result": dict(self.result),
        }


class RelayHandler(BaseHTTPRequestHandler):
    server: RelayServer

    def _write_response(
        self,
        *,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _write_html(
        self,
        *,
        status: HTTPStatus,
        badge: str,
        badge_color: str,
        title: str,
        detail: str,
        extra: str = "",
    ) -> None:
        self._write_response(
            status=status,
            content_type="text/html; charset=utf-8",
            body=render_page(
                badge=badge,
                badge_color=badge_color,
                title=title,
                detail=detail,
                extra=extra,
            ),
        )

    def _write_json(self, payload: dict[str, Any], status: HTTPStatus) -> None:
        self._write_response(
            status=status,
            content_type="application/json; charset=utf-8",
            body=json.dumps(payload, sort_keys=True).encode("utf-8"),
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._write_response(
            status=HTTPStatus.NO_CONTENT,
            content_type="text/plain; charset=utf-8",
            body=b"",
        )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/arm":
            self._write_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            content_length = 0
        raw = self.rfile.read(max(0, content_length))
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._write_json({"error": "invalid json body"}, HTTPStatus.BAD_REQUEST)
            return

        state = str(payload.get("state") or "").strip()
        forward_url = str(payload.get("forward_url") or "").strip()
        label = str(payload.get("label") or "").strip()
        console_url = str(payload.get("console_url") or "").strip()
        if not state or not forward_url:
            self._write_json(
                {
                    "error": "state and forward_url are required",
                    "status": self.server.status_payload(),
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        armed = self.server.arm_target(
            state=state,
            forward_url=forward_url,
            label=label,
            console_url=console_url,
        )
        self._write_json(
            {
                "ok": True,
                "armed": armed,
                "status": self.server.status_payload(),
            },
            HTTPStatus.ACCEPTED,
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/healthz":
            self._write_response(
                status=HTTPStatus.OK,
                content_type="text/plain; charset=utf-8",
                body=b"ok\n",
            )
            return

        if parsed.path == "/api/status":
            self._write_json(self.server.status_payload(), HTTPStatus.OK)
            return

        if parsed.path == "/arm":
            state = (params.get("state") or [""])[0].strip()
            forward_url = (params.get("forward_url") or [""])[0].strip()
            label = (params.get("label") or [""])[0].strip()
            console_url = (params.get("console_url") or [""])[0].strip()
            next_url = (params.get("next_url") or [""])[0].strip()
            if not state or not forward_url:
                self._write_html(
                    status=HTTPStatus.BAD_REQUEST,
                    badge="Missing details",
                    badge_color="var(--danger)",
                    title="Auth arm is incomplete",
                    detail="The bridge needs both a state token and a forward URL before it can relay the callback.",
                )
                return
            self.server.arm_target(
                state=state,
                forward_url=forward_url,
                label=label,
                console_url=console_url,
            )
            if next_url:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", next_url)
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.end_headers()
                return
            extra = ""
            if console_url:
                extra = f'<div><a href="{html.escape(console_url)}">Return to {html.escape(label or "console")}</a></div>'
            self._write_html(
                status=HTTPStatus.OK,
                badge="Armed",
                badge_color="var(--ok)",
                title="Auth bridge armed",
                detail="The next localhost callback for this state will be relayed to the remote bot.",
                extra=extra,
            )
            return

        if parsed.path != "/auth/callback":
            pending = self.server.status_payload().get("pending") or []
            if pending:
                items = "".join(
                    (
                        '<div class="card">'
                        f'<div class="label">{html.escape(str(item.get("label") or item.get("state") or "Pending auth"))}</div>'
                        f'<div><span class="mono">{html.escape(str(item.get("forward_url") or ""))}</span></div>'
                        + (
                            f'<div><a href="{html.escape(str(item.get("console_url") or "#"))}">Return to console</a></div>'
                            if item.get("console_url")
                            else ""
                        )
                        + "</div>"
                    )
                    for item in pending[:5]
                )
                extra = f'<div class="list">{items}</div>'
            else:
                extra = (
                    "<p>Arm the bridge from a Norman bot console before starting sign-in. "
                    "Then when OpenAI redirects back to "
                    '<span class="mono">http://localhost:1455/auth/callback?code=...&amp;state=...</span>, '
                    "this bridge will relay the callback automatically.</p>"
                )
            self._write_html(
                status=HTTPStatus.OK,
                badge="Waiting",
                badge_color="var(--warn)",
                title="Norman auth bridge is ready",
                detail="Leave this helper running, then complete the browser sign-in flow.",
                extra=extra,
            )
            return

        code = (params.get("code") or [""])[0].strip()
        state = (params.get("state") or [""])[0].strip()
        if not code or not state:
            self._write_html(
                status=HTTPStatus.BAD_REQUEST,
                badge="Blocked",
                badge_color="var(--danger)",
                title="Callback is missing details",
                detail="The browser callback did not include the expected code and state values.",
            )
            return

        target_info = self.server.pop_target(state)
        forward_url = ""
        console_url = ""
        label = ""
        if target_info:
            forward_url = str(target_info.get("forward_url") or "").strip()
            console_url = str(target_info.get("console_url") or "").strip()
            label = str(target_info.get("label") or "").strip()
        elif self.server.default_forward_url:
            forward_url = self.server.default_forward_url

        if not forward_url:
            self._write_html(
                status=HTTPStatus.CONFLICT,
                badge="No target",
                badge_color="var(--danger)",
                title="Auth callback has nowhere to go",
                detail="No armed remote callback target matched this state. Go back to the bot console and start sign-in again.",
            )
            return

        query_items = {
            "code": code,
            "state": state,
            **{
                key: values[0]
                for key, values in params.items()
                if key not in {"code", "state"} and values
            },
        }
        target = merge_forward_url_query(forward_url, query_items)
        status = HTTPStatus.ACCEPTED
        detail = "The callback was relayed to the remote bot. Return to the console."
        badge = "Delivered"
        badge_color = "var(--ok)"
        extra = f'<div class="card"><div class="label">Forwarded to</div><div><span class="mono">{html.escape(target)}</span></div></div>'
        if console_url:
            extra += f'<div><a href="{html.escape(console_url)}">Return to {html.escape(label or "console")}</a></div>'
            extra += build_return_to_console_extra(
                console_url=console_url,
                label=label,
            )
        try:
            request = Request(target, method="GET")
            with urlopen(request, timeout=20) as response:
                status = HTTPStatus(response.status)
        except HTTPError as exc:
            status = HTTPStatus(exc.code)
            badge = "Remote error"
            badge_color = "var(--danger)"
            detail = f"The remote bot rejected the callback with HTTP {exc.code}."
        except URLError as exc:
            status = HTTPStatus.BAD_GATEWAY
            badge = "Forward failed"
            badge_color = "var(--danger)"
            detail = f"Could not reach the remote bot callback: {exc.reason}."

        self.server.result = {
            "status": int(status),
            "target": target,
            "detail": detail,
            "state": state,
            "label": label,
        }
        self.server.completed.set()
        self._write_html(
            status=status,
            badge=badge,
            badge_color=badge_color,
            title="Auth callback relayed",
            detail=detail,
            extra=extra,
        )

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            f"[auth-bridge] {self.address_string()} - " + fmt % args + "\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Localhost browser auth callback relay for Norman remote bots."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1455)
    parser.add_argument(
        "--forward-url",
        default="",
        help="Optional default remote /auth/browser/callback URL",
    )
    parser.add_argument("--arm-ttl", type=int, default=900)
    args = parser.parse_args()

    server = RelayServer(
        (args.host, args.port),
        RelayHandler,
        default_forward_url=args.forward_url,
        arm_ttl_seconds=args.arm_ttl,
    )
    print(f"Listening on http://{args.host}:{args.port}/auth/callback")
    if args.forward_url:
        print(f"Default forward target: {args.forward_url}")
    print("Awaiting armed callback targets via /api/arm")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
