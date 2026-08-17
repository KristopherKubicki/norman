#!/bin/zsh

tailscale_bin="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
expressvpn_bin="/usr/local/bin/expressvpnctl"
python_bin="/usr/bin/python3"

required_bypasses=(
  "100.64.0.0/10"
  "fd7a:115c:a1e0::/48"
  "192.168.2.0/24"
)

stop_tailscale() {
  if [[ -x "${tailscale_bin}" ]]; then
    "${tailscale_bin}" down >/dev/null 2>&1 || true
  fi
}

if [[ ! -x "${tailscale_bin}" || ! -x "${expressvpn_bin}" ]]; then
  stop_tailscale
  exit 1
fi

expressvpn_settings="$("${expressvpn_bin}" --unstable dump daemon-settings 2>/dev/null)" || {
  stop_tailscale
  exit 1
}

required_json="$("${python_bin}" -c 'import json, sys; print(json.dumps(sys.argv[1:]))' \
  "${required_bypasses[@]}")"

if ! /usr/bin/printf '%s' "${expressvpn_settings}" | "${python_bin}" -c '
import json
import sys

required = set(json.loads(sys.argv[1]))
settings = json.load(sys.stdin)
bypasses = {
    rule.get("subnet")
    for rule in settings.get("bypassSubnets", [])
    if rule.get("mode") == "exclude"
}
valid = (
    settings.get("splitTunnelEnabled") is True
    and settings.get("splitTunnelDNS") is False
    and required <= bypasses
    and any(
        rule.get("mode") == "exclude"
        and rule.get("path") == "/Applications/Tailscale.app"
        for rule in settings.get("splitTunnelRules", [])
    )
)
raise SystemExit(0 if valid else 1)
' "${required_json}"; then
  stop_tailscale
  exit 1
fi

expressvpn_state="$("${expressvpn_bin}" get connectionstate 2>/dev/null)"
if [[ "${expressvpn_state}" != "Connected" ]]; then
  "${expressvpn_bin}" connect >/dev/null 2>&1 || true
  stop_tailscale
  exit 0
fi

/usr/bin/open -gja /Applications/Tailscale.app >/dev/null 2>&1 || {
  stop_tailscale
  exit 1
}

"${tailscale_bin}" set --accept-dns=false >/dev/null 2>&1 || {
  stop_tailscale
  exit 1
}

tailscale_state="$("${tailscale_bin}" status --json 2>/dev/null | \
  "${python_bin}" -c 'import json, sys; print(json.load(sys.stdin).get("BackendState", ""))' \
  2>/dev/null)"
if [[ "${tailscale_state}" != "Running" ]]; then
  "${tailscale_bin}" up >/dev/null 2>&1 || {
    stop_tailscale
    exit 1
  }
fi

tailscale_online="$("${tailscale_bin}" status --json 2>/dev/null | \
  "${python_bin}" -c 'import json, sys; print(str(json.load(sys.stdin).get("Self", {}).get("Online", False)).lower())' \
  2>/dev/null)"
if [[ "${tailscale_online}" != "true" ]]; then
  stop_tailscale
  exit 1
fi
