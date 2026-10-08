#!/usr/bin/env bash
set -euo pipefail
# Only bounded route identifiers may become SSH command arguments.
if [[ "$#" -eq 0 ]]; then
  :
elif [[ "$#" -eq 2 && "$1" == "--route" && "$2" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]]; then
  :
elif [[ "$#" -eq 1 && "$1" == "--help" ]]; then
  :
else
  echo "Usage: codex-route-policy [--route ROUTE]" >&2
  exit 2
fi
# Read public routing metadata through the existing SSH identity; no token lookup.
exec ssh -o BatchMode=yes -o ConnectTimeout=5 norman \
  python3 /usr/local/libexec/norman-routing-snapshot "$@"
