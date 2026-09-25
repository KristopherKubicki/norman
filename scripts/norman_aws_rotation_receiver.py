#!/usr/bin/env python3
"""Fixed root receiver. Credentials enter stdin; only allowlisted status leaves.

Installed root-owned and called through authenticated SSH, never as a raw secret
retrieval tool. This file does not import Norman settings or initialize a vault.
"""

import configparser
import io
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

import boto3
import botocore.session
from botocore.config import Config

VERSION = "aws-rotation-receiver-v1"
OLD_KEY = "AKIA6D72SCHDJMCBQ2OX"
PERSONAL = "970651210182"
ACCOUNTS = (PERSONAL, "104637383649", "703671901350")
PROFILES = ("kk-personal", "personal-bedrock")
HOSTS = {
    "hal": ("hal", "kristopher"),
    "norman": ("norman", "kristopher"),
    "networking": ("netops", "root"),
}
CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1})


def sts(session):
    return session.client(
        "sts",
        region_name="us-east-1",
        endpoint_url="https://sts.us-east-1.amazonaws.com",
        verify=True,
        config=CONFIG,
    )


def identity(session, account, role=False):
    result = sts(session).get_caller_identity()
    expected = (
        f"arn:aws:sts::{account}:assumed-role/CloudAgentManagement/"
        if role
        else f"arn:aws:iam::{PERSONAL}:user/cloudagent"
    )
    arn = result.get("Arn", "")
    if result.get("Account") != account or (
        not arn.startswith(expected) if role else arn != expected
    ):
        raise ValueError("identity mismatch")


def session_for(home, profile):
    core = botocore.session.Session()
    core.set_config_variable("credentials_file", str(home / ".aws/credentials"))
    core.set_config_variable("config_file", str(home / ".aws/config"))
    return boto3.Session(
        profile_name=profile, botocore_session=core, region_name="us-east-1"
    )


def parse_credentials(path, uid):
    """Read only the fixed receiver's standard credential file internally."""
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != uid
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("credential file permissions")
    if path.parent.is_symlink() or path.is_symlink() or info.st_nlink != 1:
        raise ValueError("credential path")
    if path.parent.stat().st_mode & 0o022 or info.st_size > 65536:
        raise ValueError("credential directory")
    parser = configparser.RawConfigParser()
    with path.open() as stream:
        parser.read_file(stream)
    return parser, info


def replace_profiles(path, uid, gid, key_id, secret):
    """Atomically replace existing SDK profiles with a private credential inode.

    No rollback copy is made; the old AWS key remains active. The brief sibling
    replacement file has mode 0600 and is removed on failure. No logs contain it.
    """
    parser, before = parse_credentials(path, uid)
    for profile in PROFILES:
        current = parser.get(profile, "aws_access_key_id")
        if current not in (OLD_KEY, key_id) or parser.get(
            profile, "aws_session_token", fallback=""
        ):
            raise ValueError("unexpected credentials")
        parser.set(profile, "aws_access_key_id", key_id)
        parser.set(profile, "aws_secret_access_key", secret)
    buffer = io.StringIO()
    parser.write(buffer)
    descriptor, staging = tempfile.mkstemp(
        prefix=".credentials-rotation-", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchown(stream.fileno(), uid, gid)
            stream.write(buffer.getvalue())
            stream.flush()
            os.fsync(stream.fileno())
        after = path.lstat()
        if (before.st_ino, before.st_mtime_ns, before.st_size) != (
            after.st_ino,
            after.st_mtime_ns,
            after.st_size,
        ):
            raise ValueError("concurrent credential change")
        os.replace(staging, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


def source_check(home, key_id):
    """Read fresh profiles and authenticate both; no CLI role cache is used."""
    for profile in PROFILES:
        session = session_for(home, profile)
        credentials = session.get_credentials().get_frozen_credentials()
        if credentials.access_key != key_id or credentials.token:
            raise ValueError("source key mismatch")
        identity(session, PERSONAL)
    return session_for(home, "kk-personal")


def account_check(source, account):
    """Assume a fresh role explicitly, keeping temporary credentials in memory."""
    if account == PERSONAL:
        identity(source, PERSONAL)
        return
    result = sts(source).assume_role(
        RoleArn=f"arn:aws:iam::{account}:role/CloudAgentManagement",
        RoleSessionName="norman-rotation-verify",
        DurationSeconds=900,
    )["Credentials"]
    temporary = boto3.Session(
        aws_access_key_id=result["AccessKeyId"],
        aws_secret_access_key=result["SecretAccessKey"],
        aws_session_token=result["SessionToken"],
    )
    identity(temporary, account, role=True)


def service_check(host, restart=False):
    """Refresh known cached clients on Hal; no notification is generated."""
    units = {
        "hal": ["norman-notifications.service", "norman-glimpser-alerts.service"],
        "netops": ["cloudagent-codex.service", "cloudagent-switchboard-watch.service"],
        "norman": [
            "norman-production@085a0c0f42acf4d15151a664ac748ee06897c6de.service"
        ],
    }[host]
    if restart and host == "hal":
        subprocess.run(
            ["/usr/bin/systemctl", "restart", *units],
            capture_output=True,
            check=True,
            timeout=40,
        )
    for unit in units:
        subprocess.run(
            ["/usr/bin/systemctl", "is-active", "--quiet", unit],
            capture_output=True,
            check=True,
            timeout=10,
        )
    if host in ("hal", "norman"):
        for attempt in range(20):
            try:
                http_health(host)
                return
            except (OSError, ValueError):
                if attempt == 19:
                    raise
                time.sleep(1)


def http_health(host):
    """Wait for the application listener, not merely systemd's process state."""
    url = (
        "http://192.168.2.137:8796/health"
        if host == "hal"
        else "http://127.0.0.1:8000/health"
    )
    with urllib.request.urlopen(url, timeout=5) as response:
        data = json.load(response)
    if not (data.get("ok") is True if host == "hal" else data.get("status") == "ok"):
        raise ValueError("service health")


def dummy_check():
    """Exercise replacement with synthetic profiles; never touch real profiles."""
    with tempfile.TemporaryDirectory(prefix="norman-rotation-dummy-") as temp:
        path = Path(temp) / "credentials"
        path.write_text(
            "".join(
                f"[{p}]\naws_access_key_id={OLD_KEY}\naws_secret_access_key=dummy-old\n"
                for p in PROFILES
            )
            + "[unrelated]\nregion=us-east-2\n"
        )
        path.chmod(0o600)
        replace_profiles(path, os.getuid(), os.getgid(), "dummy-new", "dummy-secret")
        parser, _ = parse_credentials(path, os.getuid())
        assert all(parser.get(p, "aws_access_key_id") == "dummy-new" for p in PROFILES)
        assert parser.get("unrelated", "region") == "us-east-2"


def handle(body, host, user):
    """Validate a fixed operation, fixed account and exact field set."""
    action = body.get("action")
    fields = {
        "dummy": {"action"},
        "ready": {"action"},
        "install": {"action", "key_id", "secret"},
        "verify": {"action", "key_id", "account_id"},
    }
    if action not in fields or set(body) != fields[action]:
        raise ValueError("request rejected")
    owner = pwd.getpwnam(user)
    home = Path(owner.pw_dir)
    if action == "dummy":
        dummy_check()
    elif action == "ready":
        parse_credentials(home / ".aws/credentials", owner.pw_uid)
        source_check(home, OLD_KEY)
        service_check(host)
    else:
        key_id = body["key_id"]
        if (
            not isinstance(key_id, str)
            or not re.fullmatch(r"AKIA[A-Z0-9]{16}", key_id)
            or key_id == OLD_KEY
        ):
            raise ValueError("replacement key rejected")
        if action == "install":
            secret = body["secret"]
            if not isinstance(secret, str) or not 20 <= len(secret) <= 128:
                raise ValueError("secret rejected")
            identity(
                boto3.Session(aws_access_key_id=key_id, aws_secret_access_key=secret),
                PERSONAL,
            )
            replace_profiles(
                home / ".aws/credentials", owner.pw_uid, owner.pw_gid, key_id, secret
            )
            source_check(home, key_id)
            service_check(host, restart=True)
        else:
            if body["account_id"] not in ACCOUNTS:
                raise ValueError("account rejected")
            account_check(source_check(home, key_id), body["account_id"])
            service_check(host)
    return {"ok": True, "version": VERSION, "host": host, "action": action}


def main():
    """Root-owned stdin receiver with fixed sanitized errors and no traceback."""
    try:
        host, user = HOSTS[socket.gethostname()]
        permitted_uid = pwd.getpwnam(user).pw_uid if host == "norman" else 0
        if os.geteuid() not in (0, permitted_uid) or len(sys.argv) != 1:
            raise ValueError("receiver identity rejected")
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversize input")
        body = json.loads(raw)
        result = handle(body, host, user)
    except Exception as exc:
        kind = type(exc).__name__
        allowed = {
            "ValueError",
            "PermissionError",
            "FileNotFoundError",
            "ClientError",
            "CalledProcessError",
            "URLError",
            "NoCredentialsError",
            "ProfileNotFound",
            "TypeError",
        }
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "receiver_failed",
                    "kind": kind if kind in allowed else "other",
                }
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
