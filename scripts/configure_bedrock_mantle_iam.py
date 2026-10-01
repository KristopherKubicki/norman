#!/usr/bin/env python3
"""Configure least-privilege IAM access for a Bedrock Mantle runner."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Sequence

import boto3


NAME_PATTERN = re.compile(r"^[A-Za-z0-9+=,.@_-]+$")
PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class ConfigurationError(RuntimeError):
    """Expected configuration or verification failure."""


def _validated(value: str, pattern: re.Pattern[str], label: str) -> str:
    cleaned = value.strip()
    if not cleaned or not pattern.fullmatch(cleaned):
        raise ConfigurationError(f"invalid {label}: {value!r}")
    return cleaned


def project_arn(account_id: str, region: str, project: str) -> str:
    account = _validated(account_id, re.compile(r"^\d{12}$"), "AWS account ID")
    aws_region = _validated(region, PROJECT_PATTERN, "AWS region")
    project_name = _validated(project, PROJECT_PATTERN, "project name")
    return f"arn:aws:bedrock-mantle:{aws_region}:{account}:project/{project_name}"


def policy_document(account_id: str, region: str, project: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "UseApprovedMantleProject",
                "Effect": "Allow",
                "Action": [
                    "bedrock-mantle:Get*",
                    "bedrock-mantle:List*",
                    "bedrock-mantle:CreateInference",
                ],
                "Resource": project_arn(account_id, region, project),
            },
            {
                "Sid": "CallMantleWithBearerToken",
                "Effect": "Allow",
                "Action": "bedrock-mantle:CallWithBearerToken",
                "Resource": "*",
            },
            {
                "Sid": "AllowMantleMarketplaceSubscription",
                "Effect": "Allow",
                "Action": [
                    "aws-marketplace:Subscribe",
                    "aws-marketplace:ViewSubscriptions",
                ],
                "Resource": "*",
                "Condition": {
                    "ForAnyValue:StringEquals": {
                        "aws:CalledViaLast": "bedrock-mantle.amazonaws.com"
                    }
                },
            },
        ],
    }


def policy_name(project: str) -> str:
    project_name = _validated(project, PROJECT_PATTERN, "project name")
    return f"norman-bedrock-mantle-{project_name}"


def _simulation_allowed(
    iam: Any, principal_arn: str, action: str, resource: str
) -> bool:
    response = iam.simulate_principal_policy(
        PolicySourceArn=principal_arn,
        ActionNames=[action],
        ResourceArns=[resource],
    )
    results = response.get("EvaluationResults", [])
    return bool(results and results[0].get("EvalDecision") == "allowed")


def _verify_policy(iam: Any, principal_arn: str, resource: str) -> None:
    checks = (
        ("bedrock-mantle:CreateInference", resource),
        ("bedrock-mantle:CallWithBearerToken", "*"),
    )
    denied = [
        action
        for action, target in checks
        if not _simulation_allowed(iam, principal_arn, action, target)
    ]
    if denied:
        raise ConfigurationError(f"IAM simulation denied: {', '.join(denied)}")


def _account_id(session: Any) -> str:
    response = session.client("sts").get_caller_identity()
    return _validated(
        str(response.get("Account", "")),
        re.compile(r"^\d{12}$"),
        "AWS account ID",
    )


def configure(args: argparse.Namespace) -> dict[str, Any]:
    user_name = _validated(args.user_name, NAME_PATTERN, "IAM user name")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    account_id = _account_id(session)
    document = policy_document(account_id, args.region, args.project)
    summary = {
        "account_id": account_id,
        "user_name": user_name,
        "policy_name": policy_name(args.project),
        "project_arn": project_arn(account_id, args.region, args.project),
        "policy_document": document,
        "applied": bool(args.apply),
    }
    if not args.apply:
        return summary
    iam = session.client("iam")
    iam.put_user_policy(
        UserName=user_name,
        PolicyName=summary["policy_name"],
        PolicyDocument=json.dumps(document, separators=(",", ":")),
    )
    principal_arn = f"arn:aws:iam::{account_id}:user/{user_name}"
    _verify_policy(iam, principal_arn, summary["project_arn"])
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="AWS CLI profile")
    parser.add_argument("--user-name", required=True, help="dedicated runner IAM user")
    parser.add_argument("--region", required=True, help="Bedrock Mantle region")
    parser.add_argument("--project", default="default", help="approved Mantle project")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write and verify the inline policy; otherwise print a dry run",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        summary = configure(parse_args(argv))
    except Exception as exc:
        print(f"Bedrock Mantle IAM configuration failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
