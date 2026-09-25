#!/usr/bin/env python3
"""Root-owned, fixed-operation signed client; prints sanitized AWS receipts only."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

URL = "https://norman.home.arpa"
NAMESPACE = "norman-keys-v1"
ACTIONS = {
    "dummy",
    "preflight",
    "cipher-test",
    "prepare",
    "distribute",
    "retire",
    "recover",
    "status",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward signed requests to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, "Redirect refused", headers, fp
        )


def call(path: str, payload: dict, public_key: str) -> dict:
    """Sign exact request bytes with the existing SSH host key; require HTTPS."""
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
    digest = hashlib.sha256(data).hexdigest()
    message = f"{NAMESPACE}\nnorman.home.arpa\nPOST\n{path}\n{timestamp}\n{nonce}\n{digest}".encode()
    signature = subprocess.run(
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "sign",
            "-f",
            "/etc/ssh/ssh_host_ed25519_key",
            "-n",
            NAMESPACE,
        ],
        input=message,
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout
    headers = {
        "Content-Type": "application/json",
        "X-Norman-Host-Key": public_key,
        "X-Norman-Host-Signature": base64.b64encode(signature).decode(),
        "X-Norman-Host-Time": timestamp,
        "X-Norman-Host-Nonce": nonce,
    }
    request = urllib.request.Request(
        URL + path, data=data, headers=headers, method="POST"
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=180) as response:
        return json.load(response)


def main() -> None:
    """Allow only fixed rotation stages for the personal account."""
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        raise SystemExit(
            "Usage: sudo norman-aws-rotation dummy|preflight|cipher-test|prepare|distribute|retire|recover|status"
        )
    config = json.loads(Path("/etc/norman-keys-host.json").read_text())
    public_key = " ".join(
        Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().split()[:2]
    )
    raw = base64.b64decode(public_key.split()[1])
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(raw).digest()
    ).decode().rstrip("=")
    identity = {"host_id": config["host_id"], "identity_fingerprint": fingerprint}
    parameters = {"account_id": "970651210182"}
    requested = call(
        "/v1/capabilities/request",
        identity
        | {
            "capability": "aws.gmail.rotation",
            "requester_type": "agent",
            "requester_id": config["requester_id"],
            "lane": config["lane"],
            "action": sys.argv[1],
            "parameters": parameters,
            "target_host": parameters["account_id"],
            "requested_ttl_seconds": 60,
            "reason": "Owner-authorized staged personal AWS key rotation",
        },
        public_key,
    )
    lease = requested.get("lease")
    if not lease:
        raise SystemExit("Capability approval is pending; no AWS operation executed")
    result = call(
        "/v1/capabilities/" + lease["lease_id"] + "/invoke",
        identity | {"parameters": parameters},
        public_key,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Broker rejected request (HTTP {exc.code})") from None
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit(
            "AWS rotation client failed; no credentials returned"
        ) from None
