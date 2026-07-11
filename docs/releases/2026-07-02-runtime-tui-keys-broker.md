# Runtime TUI Keys Broker Delta

Date: 2026-07-02
Scope: Norman Keys, console-runtime bridge, Norman/NetOps/Uplink TUIs
Status: Deployed to `norman.home.arpa`, NetOps, and Uplink

## Summary

The TUI console-runtime bridge no longer needs a direct
`NORMAN_CONSOLE_RUNTIME_TOKEN` in the NetOps/Uplink service env. Those TUIs now
resolve `norman/console-runtime-token` through Norman Keys, then use the leased
value to publish behavior/model/tool events into console-runtime.

## Changes

- Added a service-token-authenticated compatibility endpoint:
  - `POST /v1/secrets/get`
- Added Norman Keys providers for transitional secret backends:
  - `env`, for values already injected into the Norman service environment
  - `env_file`, for named values in controlled environment files
- Added `norman_keys_service_token` and `norman_keys_service_user_email`
  settings.
- Seeded production Keys records:
  - provider `norman-service-environment`
  - alias `norman/console-runtime-token`
  - policy `runtime-tui-bridge-read`
- Updated the shared TUI template to resolve runtime tokens from:
  - direct env token first, for migration compatibility
  - Norman Keys HTTP broker via `NORMAN_KEYS_URL`
  - broker command via `NORMAN_SECRET_CMD`
- Deployed `UI v2026.07.02.1` to:
  - Norman
  - NetOps networking
  - Uplink

## Live Verification

- Norman `/v1/secrets/get` returned `200` with provider `env`, a lease id, and a
  non-empty value length.
- NetOps and Uplink called Norman Keys successfully from
  `192.168.2.242`.
- Running NetOps/Uplink web service environments now have:
  - `NORMAN_CONSOLE_RUNTIME_TOKEN=absent`
  - `NORMAN_KEYS_URL=present`
  - `NORMAN_KEYS_TOKEN=present`
  - `NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET=present`
- Console-runtime jobs are still receiving TUI events after restart:
  - `norman-tui-runtime`
  - `networking-tui-runtime`
  - `uplink-tui-runtime`

## Tests

- `make format`
- `make lint`
- Focused runtime/Keys/TUI tests:
  - `tests/test_keys_api.py`
  - `tests/test_agent_console_runtime_bridge.py`
  - `tests/test_console_runtime_store.py`
