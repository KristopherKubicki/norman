# Private Auth Handoff

This is the handoff for making private-enclave bot auth work correctly on the
private host, instead of depending on a localhost callback that lands on the
operator's laptop.

## Current Problem

`PEF` on `private.home.lollie.org:8796` can be placed into browser sign-in
mode, but the current browser OAuth flow is not complete for a remote bot.

Observed behavior:

- the bot prepares a browser auth URL
- the auth URL uses `redirect_uri=http://localhost:1455/auth/callback`
- the operator opens that URL on their laptop
- the callback lands on the operator's laptop, not on the private host
- the `PEF` runtime on CT `148` is not listening on `127.0.0.1:1455`
- the login times out and the bot falls back to the sign-in chooser

So the current browser auth path is not actually valid for remote/private bots.

## What Must Be True

Private bots should keep isolated auth state:

- separate `CODEX_HOME`
- separate auth bundle
- no auth sharing with `toy-box`, `[INTERNAL_HOST]`, `hal`, or `networking-host`
- all callback handling should terminate on the private host or on a deliberate
  Norman-side relay for that private host

For `PEF`, the auth state belongs in:

- `/srv/parkergalebot/state/.codex`

It should not depend on the operator machine having a local callback listener.

## Target Model

The private host should own the browser auth callback path for private bots.

Recommended target:

- `PEF` starts browser sign-in
- the auth URL points to a callback that the private host can actually receive
- the callback completes on the private host
- the resulting auth bundle stays only in the private bot runtime

Acceptable implementations:

1. host-local callback on the private host
2. Norman-side auth relay that explicitly proxies the callback into the target
   private bot

The first option is simpler if the private host can own the whole flow.

## Recommended Immediate Plan

1. Make the private host the callback owner for private bots.
2. Give private-host Caddy an auth callback route for private bot login.
3. Update the bot sign-in launcher so the produced OAuth URL uses the private
   host callback, not operator-local `localhost:1455`.
4. Keep the auth bundle in the bot's own isolated state directory.
5. Only expose the final sign-in action through Norman/Prime as a controlled
   operator step.

## Concrete Target

For `PEF`, the concrete target should be:

- console:
  - `https://private.home.lollie.org/pef/`
- auth start:
  - `https://private.home.lollie.org/pef/auth/start`
- auth callback:
  - `https://private.home.lollie.org/pef/auth/callback`

That gives one stable host and one obvious per-bot path shape.

The browser auth URL produced for `PEF` should eventually use:

- `redirect_uri=https://private.home.lollie.org/pef/auth/callback`

not:

- `redirect_uri=http://localhost:1455/auth/callback`

## Concrete Caddy Shape

The private host should have host-local Caddy routes that look roughly like:

```caddy
private.home.lollie.org {
    handle_path /pef/* {
        reverse_proxy 127.0.0.1:8796
    }

    handle /pef/auth/callback* {
        reverse_proxy 127.0.0.1:1455
    }
}
```

If the callback listener does not live in the Codex process directly, the same
route can proxy to a tiny local auth-helper bound only on loopback, for example:

- `127.0.0.1:1455` for `PEF`
- `127.0.0.1:1456` for future `health`
- `127.0.0.1:1457` for future `finance`

The important point is that the callback terminates on the private host, not on
the operator laptop.

## Container/Listener Shape

Because `PEF` is a containerized private bot runtime, it needs one of these:

1. the Codex runtime itself listens for the callback on loopback
2. a tiny sidecar helper listens on loopback and writes the auth bundle into the
   bot's `CODEX_HOME`

The sidecar option is acceptable if it stays within the same trust boundary and
only writes into:

- `/srv/parkergalebot/state/.codex`

The sidecar should not hold shared auth for any other bot.

## Norman Fallback Relay

If the private host cannot own the callback cleanly yet, Norman can act as a
relay, but only as a fallback.

Fallback shape:

- Norman receives:
  - `https://norman.[INTERNAL_DOMAIN]/bot/pef/auth/callback`
- Norman validates a short-lived relay token tied to the target bot
- Norman forwards the callback payload into the private host over a deliberate
  internal endpoint
- the private bot writes the resulting auth into its own isolated state

If this fallback is used, Norman should not persist the resulting private auth
bundle. Norman should only broker the callback.

## Recommended Implementation Order

1. Add host-local path proxying on `private.home.lollie.org` so raw port `8796`
   is no longer the primary operator path.
2. Add a private-host callback listener path for `PEF`.
3. Change `PEF` browser-sign-in preparation so it emits the private-host
   callback URL.
4. Verify the resulting auth lands in `/srv/parkergalebot/state/.codex`.
5. Only if that is blocked, add the Norman relay fallback.

## Relation To Existing Norman Proxy Work

Norman already has a bot-proxy renderer for ordinary console paths in:

- `scripts/render_norman_bot_proxy_caddy.py`

That path model is useful for normal bot browsing, but private auth should not
assume Norman owns the credential landing zone by default. For private bots,
host-local callback ownership is the preferred design.

## Norman's Role

Norman should still be the control plane, but not the storage location for
private bot credentials.

Norman should:

- detect `needs auth`
- expose `Browser Sign-In`
- show whether the callback is waiting, failed, or complete
- link the operator into the right flow

Norman should not:

- store the private auth token itself if the bot can own it locally
- collapse private auth into a shared fleet auth bundle

## Private-Host/Caddy Work

Private host needs:

- a stable hostname: `private.home.lollie.org`
- a callback path for private bot auth
- clean local routing for the private bot console
- eventual HTTPS, so auth/browser flows do not stay on raw insecure ports

Likely end-state examples:

- `https://private.home.lollie.org/pef/`
- `https://private.home.lollie.org/auth/pef/callback`

or, if per-bot naming is preferred:

- `https://pef.private.home.lollie.org/`
- `https://pef.private.home.lollie.org/auth/callback`

## Fallbacks

If the callback work is not ready yet, the clean fallback order is:

1. proper Norman/private-host browser callback relay
2. device-code auth if explicitly enabled for the account
3. API-key auth if that is acceptable for the private bot's usage/billing model

The bad fallback is:

- continuing to hand the operator a `localhost:1455` callback URL for a bot
  that lives on a remote container

## Success Criteria

This handoff is complete when:

- `PEF` can be signed in from the web
- the callback lands on the private host or a deliberate relay
- the resulting auth persists in the private bot runtime
- the console no longer times out back to the sign-in chooser
- private auth remains isolated from the rest of the fleet
