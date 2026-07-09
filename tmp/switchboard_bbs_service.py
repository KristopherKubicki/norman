#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


STATE_LABELS = {
    "blocked": "Blocked",
    "done": "Done",
    "picked_up": "Picked up",
    "waiting_pickup": "Waiting pickup",
    "owner_offline": "Owner offline",
}


class SwitchboardHandler(BaseHTTPRequestHandler):
    artifact_dir: Path

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _thread_loop_state(
        self, thread: dict[str, Any], posts: list[dict[str, Any]]
    ) -> dict[str, str]:
        status = str(thread.get("status") or "").strip().lower()
        if status == "blocked":
            return {"state": "blocked", "label": STATE_LABELS["blocked"]}

        for post in sorted(
            posts,
            key=lambda item: str(item.get("posted_at") or ""),
            reverse=True,
        ):
            metadata = post.get("metadata")
            if not isinstance(metadata, dict):
                continue
            state = str(metadata.get("loop_state") or "").strip().lower()
            if state:
                return {"state": state, "label": STATE_LABELS.get(state, state)}

        state = status or "waiting_pickup"
        return {"state": state, "label": STATE_LABELS.get(state, state)}

    def _artifact_path(self, filename: str) -> Path:
        clean = str(filename or "").strip()
        candidate = Path(clean)
        if (
            not clean
            or candidate.name != clean
            or candidate.name in {".", ".."}
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError("invalid_artifact")
        root = self.artifact_dir.resolve()
        target = (root / candidate.name).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("invalid_artifact") from exc
        return target

    def _write_artifact_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        target = self._artifact_path(str(payload.get("filename") or ""))
        if "content_base64" in payload:
            try:
                data = base64.b64decode(str(payload.get("content_base64") or ""))
            except Exception as exc:  # pragma: no cover - defensive server path
                raise ValueError("invalid_artifact_content") from exc
        else:
            data = str(payload.get("content_text") or "").encode("utf-8")

        digest = hashlib.sha256(data).hexdigest()
        expected = str(payload.get("sha256") or "").strip().lower()
        if expected and expected != digest:
            raise ValueError("artifact_sha256_mismatch")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        label = str(payload.get("label") or target.name)
        return {
            "label": label,
            "href": f"/artifacts/{target.name}",
            "bytes": len(data),
            "sha256": digest,
        }

    def _capabilities(self) -> dict[str, Any]:
        return {
            "service": "switchboard-bbs",
            "endpoints": {
                "capabilities": "GET /api/v1/capabilities",
                "artifact": "GET /artifacts/{filename}",
                "upload_artifact": "POST /api/v1/artifacts",
            },
        }

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/capabilities":
            self._send_json({"capabilities": self._capabilities()})
            return
        if parsed.path.startswith("/artifacts/"):
            try:
                target = self._artifact_path(unquote(parsed.path.rsplit("/", 1)[-1]))
            except ValueError:
                self.send_error(404)
                return
            if not target.exists():
                self.send_error(404)
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/artifacts":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            artifact = self._write_artifact_from_payload(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"artifact": artifact}, status=201)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Switchboard BBS service.")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root-dir", default="/var/lib/switchboard-bbs")
    parser.add_argument("--token-dir", default="")
    parser.add_argument("--bot-directory", default="")
    parser.add_argument("--tag-taxonomy", default="")
    args = parser.parse_args()

    artifact_dir = Path(args.root_dir) / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    SwitchboardHandler.artifact_dir = artifact_dir
    server = ThreadingHTTPServer((args.bind, args.port), SwitchboardHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
