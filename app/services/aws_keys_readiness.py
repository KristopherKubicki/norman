"""Candidate server-side AWS readiness executor; not registered or enabled.

Uses existing SDK profiles without exporting credentials. It cannot import keys,
execute arbitrary AWS operations, or change account resources.
"""

from __future__ import annotations

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


ACCOUNTS = {
    "970651210182": ("kk-personal", "arn:aws:iam::970651210182:user/cloudagent"),
    "104637383649": (
        "kk-acm",
        "arn:aws:sts::104637383649:assumed-role/CloudAgentManagement/",
    ),
    "703671901350": (
        "kk-yhix",
        "arn:aws:sts::703671901350:assumed-role/CloudAgentManagement/",
    ),
}
CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 2})


class AWSReadinessError(Exception):
    """Contain a fixed public error code, never an underlying SDK response."""


def _client(session: boto3.Session, service: str) -> BaseClient:
    """Pin the service endpoint and region instead of accepting caller URLs."""
    endpoint = (
        "https://iam.amazonaws.com"
        if service == "iam"
        else "https://sts.us-east-1.amazonaws.com"
    )
    return session.client(
        service,
        region_name="us-east-1",
        endpoint_url=endpoint,
        config=CONFIG,
        verify=True,
    )


def _inspect(account: str) -> dict[str, str | bool]:
    """Verify the principal before making the fixed IAM summary request."""
    profile, expected_arn = ACCOUNTS[account]
    session = boto3.Session(profile_name=profile, region_name="us-east-1")
    identity = _client(session, "sts").get_caller_identity()
    arn = identity.get("Arn", "")
    matches = (
        isinstance(arn, str)
        and arn.startswith(expected_arn)
        and bool(arn.removeprefix(expected_arn))
        if expected_arn.endswith("/")
        else arn == expected_arn
    )
    if identity.get("Account") != account or not matches:
        raise AWSReadinessError("aws_identity_mismatch")
    summary = _client(session, "iam").get_account_summary().get("SummaryMap", {})
    mfa = summary.get("AccountMFAEnabled")
    if type(mfa) is not int or mfa not in (0, 1):
        raise AWSReadinessError("aws_summary_invalid")
    return {
        "account_id": account,
        "identity_verified": True,
        "root_mfa_enabled": bool(mfa),
    }


def execute_readiness(
    *, executor_ref: str, action: str, parameters: dict
) -> dict[str, str | bool]:
    """Run a fixed read-only operation for a server-bound personal account.

    The broker must validate enrollment, policy, approval, expiry and the lease
    parameter hash before dispatch. This module does not grant authorization.
    """
    if executor_ref not in ACCOUNTS:
        raise AWSReadinessError("aws_account_not_allowed")
    if action != "inspect" or parameters != {"account_id": executor_ref}:
        raise AWSReadinessError("aws_request_not_allowed")
    try:
        return _inspect(executor_ref)
    except (BotoCoreError, ClientError):
        raise AWSReadinessError("aws_check_failed") from None
