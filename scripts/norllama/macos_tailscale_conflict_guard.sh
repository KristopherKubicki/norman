#!/bin/zsh

# ExpressVPN is the selected VPN on this host. Tailscale must remain stopped
# because both clients claim overlapping CGNAT routes and can deadlock configd.
tailscale_bin="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
expressvpn_bin="/usr/local/bin/expressvpnctl"

if [[ -x "${tailscale_bin}" ]]; then
  "${tailscale_bin}" down >/dev/null 2>&1 || true
fi

/usr/bin/pkill -x Tailscale >/dev/null 2>&1 || true

if [[ -x "${expressvpn_bin}" ]]; then
  expressvpn_status="$("${expressvpn_bin}" status 2>/dev/null | /usr/bin/head -1)"
  if [[ "${expressvpn_status}" == "Disconnected" ]]; then
    "${expressvpn_bin}" connect >/dev/null 2>&1 || true
  fi
fi
