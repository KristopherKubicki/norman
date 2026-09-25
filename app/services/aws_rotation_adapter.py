"""Fixed-account AWS adapter; host transport must be supplied by deployment.

No default host transport, public endpoint, or capability registration is provided.
Callers must hold the workflow lock and use authenticated injected receivers.
"""

from typing import Protocol

import boto3
from botocore.config import Config
from botocore.client import BaseClient

from app.services.aws_key_rotation import CONSUMERS
from app.services.aws_rotation_store import ACCOUNT, OLD_KEY, RotationError

CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1})
PRINCIPAL = f"arn:aws:iam::{ACCOUNT}:user/cloudagent"


class HostTransport(Protocol):
    """Fixed receiver operations, not caller-supplied shell commands or URLs."""

    def ready(self, consumer: str) -> bool:
        """Verify pinned host, receiver version, expected profiles and old key."""
        ...

    def install(self, consumer: str, key_id: str, secret: str) -> None:
        """Inject over authenticated encrypted transport; no logs or key output."""
        ...

    def verify(self, consumer: str, account: str, key_id: str) -> bool:
        """Verify uncached identity and relevant application health."""
        ...


def client(session: boto3.Session, service: str) -> BaseClient:
    """Pin TLS endpoints and disable SDK retries for non-idempotent creation."""
    endpoint = {
        "iam": "https://iam.amazonaws.com",
        "sts": "https://sts.us-east-1.amazonaws.com",
    }[service]
    return session.client(
        service,
        region_name="us-east-1",
        endpoint_url=endpoint,
        verify=True,
        config=CONFIG,
    )


def verify_identity(session: boto3.Session) -> None:
    """Require the exact fixed IAM principal, never just an account match."""
    identity = client(session, "sts").get_caller_identity()
    if identity.get("Account") != ACCOUNT or identity.get("Arn") != PRINCIPAL:
        raise RotationError("rotation_identity_mismatch")


class AWSRotationAdapter:
    """AWS operations inside the trusted executor, returning no raw SDK objects."""

    def __init__(self, transport: HostTransport) -> None:
        self.transport = transport
        self.source = None
        self.preflight_passed = False

    def preflight(self) -> bool:
        """Check source key, AWS identity, slot availability and every receiver."""
        self.preflight_passed = False
        self.source = boto3.Session(profile_name="kk-personal", region_name="us-east-1")
        credentials = self.source.get_credentials().get_frozen_credentials()
        if credentials.access_key != OLD_KEY or credentials.token:
            return False
        verify_identity(self.source)
        response = client(self.source, "iam").list_access_keys(UserName="cloudagent")
        keys = response.get("AccessKeyMetadata", [])
        if response.get("IsTruncated") or len(keys) != 1:
            return False
        if keys[0].get("AccessKeyId") != OLD_KEY or keys[0].get("Status") != "Active":
            return False
        self.preflight_passed = all(
            self.transport.ready(consumer) is True for consumer in CONSUMERS
        )
        return self.preflight_passed

    def create(self) -> tuple[str, str]:
        """Create once after the workflow has durably reserved this rotation."""
        if self.source is None or not self.preflight_passed:
            raise RotationError("rotation_preflight_required")
        self.preflight_passed = False
        key = client(self.source, "iam").create_access_key(UserName="cloudagent")[
            "AccessKey"
        ]
        if key.get("UserName") != "cloudagent" or key.get("Status") != "Active":
            raise RotationError("rotation_create_response_invalid")
        return key["AccessKeyId"], key["SecretAccessKey"]

    def install(self, consumer: str, key_id: str, secret: str) -> None:
        """Delegate only to the configured trusted receiver."""
        self.transport.install(consumer, key_id, secret)

    def verify(self, consumer: str, account: str, key_id: str) -> bool:
        """Delegate fresh credential and workload verification."""
        return self.transport.verify(consumer, account, key_id)

    def set_old_active(self, key_id: str, secret: str, active: bool) -> None:
        """Authenticate with replacement credentials and change only OLD_KEY."""
        if not key_id or key_id == OLD_KEY:
            raise RotationError("rotation_replacement_required")
        session = boto3.Session(
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name="us-east-1",
        )
        verify_identity(session)
        iam = client(session, "iam")
        status = "Active" if active else "Inactive"
        iam.update_access_key(UserName="cloudagent", AccessKeyId=OLD_KEY, Status=status)
        response = iam.list_access_keys(UserName="cloudagent")
        keys = {
            item["AccessKeyId"]: item["Status"]
            for item in response.get("AccessKeyMetadata", [])
        }
        if (
            response.get("IsTruncated")
            or keys.get(OLD_KEY) != status
            or keys.get(key_id) != "Active"
        ):
            raise RotationError("rotation_status_unverified")
