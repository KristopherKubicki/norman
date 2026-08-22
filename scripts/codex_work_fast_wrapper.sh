#!/usr/bin/env bash
set -euo pipefail

# Optional app connectors are intentionally disabled only through this wrapper.
exec "$HOME/.local/bin/codex-work" --work-no-apps "$@"
