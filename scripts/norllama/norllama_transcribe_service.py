#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socketserver
import tempfile
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8097
DEFAULT_MODEL = "faster-whisper:base"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"

MODEL = os.getenv("NORLLAMA_TRANSCRIBE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
DEVICE = (
    os.getenv("NORLLAMA_TRANSCRIBE_DEVICE", DEFAULT_DEVICE).strip() or DEFAULT_DEVICE
)
COMPUTE_TYPE = (
    os.getenv("NORLLAMA_TRANSCRIBE_COMPUTE_TYPE", DEFAULT_COMPUTE_TYPE).strip()
    or DEFAULT_COMPUTE_TYPE
)
API_KEY = os.getenv("NORLLAMA_TRANSCRIBE_API_KEY", "").strip()
API_KEY_FILE = os.getenv("NORLLAMA_TRANSCRIBE_API_KEY_FILE", "").strip()

_model_lock = threading.Lock()
_model: Any = None
_model_error = ""
_model_loaded_at = 0.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _public_model_name(value: str) -> str:
    clean = _clean(value)
    if clean.startswith("faster-whisper:"):
        return clean
    return f"faster-whisper:{clean}" if clean else DEFAULT_MODEL


def _faster_whisper_model_id(value: str) -> str:
    clean = _clean(value)
    return clean.split(":", 1)[1] if clean.startswith("faster-whisper:") else clean


def _load_key() -> str:
    if API_KEY:
        return API_KEY
    if API_KEY_FILE:
        try:
            return Path(API_KEY_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def _load_model():
    global _model, _model_error, _model_loaded_at
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                _faster_whisper_model_id(MODEL),
                device=DEVICE,
                compute_type=COMPUTE_TYPE,
            )
            _model_error = ""
            _model_loaded_at = time.time()
            return _model
        except Exception as exc:
            _model_error = str(exc)[:500]
            raise


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "norllama-transcribe/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Norllama-Transcribe-Model", _public_model_name(MODEL))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = _load_key()
        if not expected:
            return True
        header = self.headers.get("Authorization", "").strip()
        if not header.startswith("Bearer "):
            return False
        return header.removeprefix("Bearer ").strip() == expected

    def do_GET(self) -> None:
        if self.path.rstrip("/") in {"", "/health", "/healthz"}:
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "status": "ok",
                    "service": "norllama-transcribe",
                    "model": _public_model_name(MODEL),
                    "backend": "faster-whisper",
                    "device": DEVICE,
                    "compute_type": COMPUTE_TYPE,
                    "loaded": _model is not None,
                    "loaded_at": _model_loaded_at,
                    "last_error": _model_error,
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0].rstrip("/") not in {
            "/transcribe",
            "/v1/audio/transcriptions",
        }:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            self._send_json(
                HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"}
            )
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send_json(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty_audio"}
            )
            return
        audio = self.rfile.read(length)
        filename = _clean(self.headers.get("X-Filename")) or "upload.wav"
        suffix = Path(filename).suffix or ".wav"
        started = time.perf_counter()
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                temp_path = handle.name
                handle.write(audio)
            model = _load_model()
            segments_iter, info = model.transcribe(
                temp_path,
                beam_size=1,
                vad_filter=True,
                word_timestamps=False,
            )
            segments = [
                {
                    "id": index,
                    "start": round(float(segment.start or 0), 3),
                    "end": round(float(segment.end or 0), 3),
                    "text": _clean(segment.text),
                }
                for index, segment in enumerate(segments_iter)
            ]
            text = " ".join(segment["text"] for segment in segments).strip()
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "request_id": uuid.uuid4().hex,
                    "model": _public_model_name(MODEL),
                    "backend": "faster-whisper",
                    "text": text,
                    "segments": segments,
                    "language": _clean(getattr(info, "language", "")),
                    "language_probability": float(
                        getattr(info, "language_probability", 0.0) or 0.0
                    ),
                    "duration": float(getattr(info, "duration", 0.0) or 0.0),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                },
            )
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "transcribe_failed", "detail": str(exc)[:500]},
            )
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    bind = os.getenv("NORLLAMA_TRANSCRIBE_BIND", DEFAULT_BIND).strip() or DEFAULT_BIND
    port = int(os.getenv("NORLLAMA_TRANSCRIBE_PORT", str(DEFAULT_PORT)) or DEFAULT_PORT)
    server = ThreadingHTTPServer((bind, port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
