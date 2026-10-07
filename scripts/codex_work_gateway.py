#!/usr/bin/env python3
"""Keep generic work inference independent of individual application gateways."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

WORK_ENDPOINT = "https://norman.home.arpa/work/v1"
# The gateway currently uses one brokered bearer token. Ownership comes from
# the trusted front-door route and server-owned AWS registry, not alias names.
WORK_TOKEN_SECRET = "norman/prompt-proxy-token"


def work_gateway_profile(contents: str, token_helper: Path) -> str:
    """Update only provider transport/auth fields; retain models and MCP config."""
    tomllib.loads(contents)
    sections = {
        "model_providers.norman": {
            "name": "Work model gateway",
            "base_url": WORK_ENDPOINT,
            "wire_api": "responses",
        },
        "model_providers.norman.auth": {
            "command": str(token_helper),
            "args": ["--secret", WORK_TOKEN_SECRET],
        },
    }
    for section, fields in sections.items():
        pattern = re.compile(
            r"(?ms)^\[" + re.escape(section) + r"\][^\n]*\n.*?(?=^\[|\Z)"
        )
        match = pattern.search(contents)
        block = match.group(0) if match else f"[{section}]\n"
        for key, value in fields.items():
            line = f"{key} = {json.dumps(value)}"
            key_pattern = re.compile(r"(?m)^\s*" + re.escape(key) + r"\s*=.*$")
            block = (
                key_pattern.sub(lambda _: line, block, count=1)
                if key_pattern.search(block)
                else block.rstrip() + "\n" + line + "\n"
            )
        contents = (
            contents[: match.start()] + block + contents[match.end() :]
            if match
            else contents.rstrip() + "\n\n" + block
        )
    provider = tomllib.loads(contents)["model_providers"]["norman"]
    if provider["base_url"] != WORK_ENDPOINT or provider["auth"]["args"] != [
        "--secret",
        WORK_TOKEN_SECRET,
    ]:
        raise ValueError("Work gateway contract could not be established")
    return contents


def update_profile(path: Path) -> None:
    """Replace the profile atomically without touching any session history."""
    before = path.read_text()
    after = work_gateway_profile(
        before, Path(__file__).with_name("norman_codex_gateway_token.py")
    )
    if before == after:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        update_profile(args.profile_file)
    except (OSError, ValueError):
        parser.exit(
            1,
            "Unable to update the generic work gateway profile; original profile retained.\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
