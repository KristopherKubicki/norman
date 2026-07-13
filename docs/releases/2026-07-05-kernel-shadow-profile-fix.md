# Kernel Shadow Profile Fix

Date: 2026-07-05
Scope: shared agent console template, Norman, toy-box, and networking TUIs
Status: deployed to the active Norman, toy-box, and networking console fleet

## Summary

`UI v2026.07.05.4` removes the stale Codex profile override that caused Bedrock
TUI turns to fail with:

```text
legacy `profile = "personal-bedrock"` config is no longer supported
```

Codex now selects profile files with `--profile <name>` and loads
`$CODEX_HOME/<name>.config.toml`. The TUI template still supports older
`--profile-v2` installs as a fallback, but it no longer passes
`-c profile="<name>"`.

The follow-up `.4` patch also stops sending OpenAI-only `service_tier` config
for profile-backed Bedrock routes. This fixes the Uplink failure:

```text
'priority' is not supported for 'service_tier' on this model
```

## Changes

- Prefer `--profile` for Codex profile-file selection.
- Remove the deprecated `profile = ...` one-shot config override from web and
  launcher paths.
- Omit `-c service_tier=...` when a Codex profile file backs the route.
- Clean legacy top-level `profile = ...` selectors and `[profiles.*]` sections
  from dedicated TUI Codex homes, including base `config.toml`, so old Codex
  installs do not leak stale `service_tier = "fast"` settings into Bedrock.
- Keep Bedrock profile environment names stable for compatibility.
- Keep `kernel_shadow` enabled on selected test consoles without changing the
  execution backend.

## Verification

- `make format`
- `make lint`
- `make test`
- Full test suite: `910 passed, 5 warnings`.
- Live status checks on Norman, toy-box, and networking TUIs after deployment.
