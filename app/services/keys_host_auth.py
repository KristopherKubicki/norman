"""Authenticate exact broker requests using enrolled OpenSSH host identities."""

from __future__ import annotations

import base64
import hashlib
import re
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import KeysHostEnrollment, KeysTransportNonce

NAMESPACE = "norman-keys-v1"


def signed_message(path: str, body: bytes, timestamp: str, nonce: str) -> bytes:
    """Bind method, audience, route, exact body, freshness, and nonce."""
    digest = hashlib.sha256(body).hexdigest()
    return f"{NAMESPACE}\nnorman.home.arpa\nPOST\n{path}\n{timestamp}\n{nonce}\n{digest}".encode()


def _verify(public_key: str, signature: bytes, message: bytes) -> None:
    """Use OpenSSH's verifier; transient files contain only public material."""
    with tempfile.TemporaryDirectory(prefix="keys-verify-") as folder:
        directory = Path(folder)
        (directory / "allowed").write_text(f"enrolled-host {public_key}\n")
        (directory / "signature").write_bytes(signature)
        try:
            result = subprocess.run(
                [
                    "/usr/bin/ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(directory / "allowed"),
                    "-I",
                    "enrolled-host",
                    "-n",
                    NAMESPACE,
                    "-s",
                    str(directory / "signature"),
                ],
                input=message,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise HTTPException(
                503, "Host signature verification unavailable"
            ) from None
        if result.returncode:
            raise HTTPException(401, "Host signature rejected")


def authenticate_host(
    db: Session,
    *,
    host_id: str,
    path: str,
    body: bytes,
    public_key: str,
    signature: str,
    timestamp: str,
    nonce: str,
) -> str:
    """Verify an enrolled host and atomically consume its signed nonce."""
    now = int(time.time())
    if (
        len(body) > 16384
        or len(public_key) > 512
        or len(signature) > 4096
        or not re.fullmatch(r"[0-9]{10}", timestamp)
        or abs(now - int(timestamp)) > 60
        or not re.fullmatch(r"[a-f0-9]{32}", nonce)
    ):
        raise HTTPException(401, "Invalid or expired host proof")
    try:
        kind, encoded = public_key.split()
        if kind != "ssh-ed25519":
            raise ValueError("Unsupported key")
        raw = base64.b64decode(encoded, validate=True)
        proof = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(401, "Invalid host proof encoding") from None
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(raw).digest()
    ).decode().rstrip("=")
    enrollment = (
        db.query(KeysHostEnrollment).filter_by(host_id=host_id, status="active").first()
    )
    if enrollment is None or enrollment.identity_fingerprint != fingerprint:
        raise HTTPException(403, "Signing host is not enrolled")
    _verify(public_key, proof, signed_message(path, body, timestamp, nonce))
    replay_id = hashlib.sha256(f"{fingerprint}:{nonce}".encode()).hexdigest()
    db.query(KeysTransportNonce).filter(KeysTransportNonce.expires_at < now).delete()
    db.add(KeysTransportNonce(digest=replay_id, expires_at=now + 121))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Host proof already used") from None
    return fingerprint
