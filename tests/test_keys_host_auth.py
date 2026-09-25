"""Exercise real OpenSSH signatures and durable replay protection."""

import base64
import subprocess
import time
import uuid
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.models import KeysHostEnrollment
from app.services.keys_host_auth import authenticate_host, signed_message, NAMESPACE


@pytest.fixture
def proof(tmp_path, db):
    key = tmp_path / "host"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    pub = " ".join(key.with_suffix(".pub").read_text().split()[:2])
    fingerprint = subprocess.check_output(
        ["ssh-keygen", "-lf", str(key) + ".pub"], text=True
    ).split()[1]
    host = "proof-" + uuid.uuid4().hex
    db.add(
        KeysHostEnrollment(
            host_id=host,
            hostname=host,
            identity_fingerprint=fingerprint,
            status="active",
            requester_ids=[],
            capability_names=[],
            lanes=[],
        )
    )
    db.commit()
    args = dict(
        host_id=host,
        path="/v1/capabilities/request",
        body=b'{"example":1}',
        public_key=pub,
        timestamp=str(int(time.time())),
        nonce=uuid.uuid4().hex,
    )
    message = signed_message(
        args["path"], args["body"], args["timestamp"], args["nonce"]
    )
    signed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", NAMESPACE],
        input=message,
        capture_output=True,
        check=True,
    ).stdout
    args["signature"] = base64.b64encode(signed).decode()
    return args, fingerprint


def test_valid_signature_and_replay(db, proof):
    args, fingerprint = proof
    assert authenticate_host(db, **args) == fingerprint
    with pytest.raises(HTTPException) as error:
        authenticate_host(db, **args)
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"body": b'{"example":2}'},
        {"path": "/v1/capabilities/other/invoke"},
        {"host_id": "forged"},
        {"signature": "invalid"},
        {"timestamp": "1000000000"},
        {"nonce": "f" * 32},
        {"public_key": "ssh-ed25519 AAAA"},
    ],
)
def test_tampering_rejected(db, proof, change):
    with pytest.raises(HTTPException) as error:
        authenticate_host(db, **(proof[0] | change))
    assert error.value.status_code in (401, 403)


def test_revoked_host_rejected(db, proof):
    args, _ = proof
    host = db.query(KeysHostEnrollment).filter_by(host_id=args["host_id"]).one()
    host.status = "revoked"
    db.commit()
    with pytest.raises(HTTPException) as error:
        authenticate_host(db, **args)
    assert error.value.status_code == 403


def test_unsigned_api_cannot_use_fingerprint_header(test_app):
    response = test_app.post(
        "/v1/capabilities/request",
        headers={"X-Norman-Keys-Host-Fingerprint": "SHA256:spoofed"},
        json={"host_id": "hal"},
    )
    assert response.status_code == 401


def test_signed_api_roundtrip_uses_verified_identity(
    test_app, db, proof, tmp_path, monkeypatch
):
    import json
    from app.api import keys_auth
    from app.models import User

    monkeypatch.setattr(
        keys_auth.settings, "norman_keys_service_user_email", "test@example.com"
    )
    monkeypatch.setattr(
        keys_auth,
        "_cached_or_db_user_for_service_token",
        lambda db, **kwargs: db.query(User).first(),
    )
    args, fingerprint = proof
    name = "signed." + uuid.uuid4().hex
    assert (
        test_app.post(
            "/api/v1/keys/capabilities",
            json={
                "name": name,
                "executor_kind": "receipt",
                "enabled": True,
            },
        ).status_code
        == 201
    )
    assert (
        test_app.post(
            "/api/v1/keys/capability-policies",
            json={
                "name": name,
                "capability_name": name,
                "requester_type": "agent",
                "requester_id": "signed-client",
                "lane": "personal",
                "allowed_actions": ["inspect"],
                "allowed_target_hosts": ["target"],
                "approval_required": False,
                "enabled": True,
            },
        ).status_code
        == 201
    )

    def post(path, payload):
        body = json.dumps(payload).encode()
        timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
        signed = subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-f", str(tmp_path / "host"), "-n", NAMESPACE],
            input=signed_message(path, body, timestamp, nonce),
            capture_output=True,
            check=True,
        ).stdout
        return test_app.post(
            path,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Norman-Host-Key": args["public_key"],
                "X-Norman-Host-Signature": base64.b64encode(signed).decode(),
                "X-Norman-Host-Time": timestamp,
                "X-Norman-Host-Nonce": nonce,
                "X-Norman-Keys-Host-Fingerprint": "SHA256:untrusted-header-ignored",
            },
        )

    identity = {"host_id": args["host_id"], "identity_fingerprint": fingerprint}
    response = post(
        "/v1/capabilities/request",
        identity
        | {
            "capability": name,
            "requester_type": "agent",
            "requester_id": "signed-client",
            "lane": "personal",
            "action": "inspect",
            "parameters": {},
            "target_host": "target",
        },
    )
    assert response.status_code == 200, response.text
    lease_id = response.json()["lease"]["lease_id"]
    receipt = post(f"/v1/capabilities/{lease_id}/invoke", identity | {"parameters": {}})
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["status"] == "completed"
