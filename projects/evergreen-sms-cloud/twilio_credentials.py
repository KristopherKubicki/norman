"""Secret-backed Twilio credentials for Evergreen SMS Lambda functions."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import boto3


_TOKEN_CACHE: dict[str, str] = {}
_TOKEN_KEYS = ("TWILIO_AUTH_TOKEN", "auth_token", "token")


def _secret_text(response: dict[str, Any]) -> str:
    direct = response.get("SecretString")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    binary = response.get("SecretBinary")
    if isinstance(binary, bytes):
        return binary.decode("utf-8").strip()
    if isinstance(binary, str) and binary.strip():
        return base64.b64decode(binary).decode("utf-8").strip()
    return ""


def _token_from_secret(secret: str) -> str:
    try:
        parsed = json.loads(secret)
    except json.JSONDecodeError:
        return secret.strip()
    if not isinstance(parsed, dict):
        return ""
    for key in _TOKEN_KEYS:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def twilio_auth_token() -> str:
    """Return the configured Twilio token without exposing it in Lambda env."""
    secret_arn = os.environ.get("TWILIO_AUTH_TOKEN_SECRET_ARN", "").strip()
    if secret_arn:
        cached = _TOKEN_CACHE.get(secret_arn)
        if cached:
            return cached
        try:
            response = boto3.client("secretsmanager").get_secret_value(
                SecretId=secret_arn
            )
            token = _token_from_secret(_secret_text(response))
        except Exception as exc:
            raise RuntimeError(
                "could not load the configured Twilio auth token secret"
            ) from exc
        if not token:
            raise RuntimeError("configured Twilio auth token secret is empty")
        _TOKEN_CACHE[secret_arn] = token
        return token

    local_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if local_token:
        return local_token
    raise RuntimeError(
        "TWILIO_AUTH_TOKEN_SECRET_ARN is required outside local development"
    )
