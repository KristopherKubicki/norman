#!/usr/bin/env bash
set -euo pipefail

# This broker exposes only the dedicated Norllama fleet BBS posting credential.
readonly TOKEN_PATH="/etc/norman/credentials/norllama-fleet-bbs.token"
readonly TOKEN_ALIAS="bbs.norllama-fleet.post-token"

if [[ "$#" -ne 2 || "$1" != "get" || "$2" != "$TOKEN_ALIAS" ]]; then
    exit 64
fi

if [[ ! -r "$TOKEN_PATH" ]]; then
    exit 66
fi

exec /usr/bin/cat "$TOKEN_PATH"
