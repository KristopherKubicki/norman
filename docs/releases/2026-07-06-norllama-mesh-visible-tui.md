# Norllama Mesh Visible TUI

Date: 2026-07-06
Scope: Norman LLM status APIs, Norllama gateway client, runtime capabilities,
shared TUI template, and fleet rollout
Status: deployed to Norman, toy-box, and networking-host

## Summary

`UI v2026.07.06.2` makes Norllama mesh state visible to the Norman runtime and
standalone TUIs. This is the next slice of the local-first control loop: the TUI
can see not only that local inference is available, but also the mesh/frontdoor
context behind that decision.

## Changes

- Add a configured Norllama worker roster for `2.133`, `2.150`, and `2.151`.
- Add a sanitized mesh snapshot builder that probes the frontdoor and direct
  Norllama worker gateways without exposing credentials.
- Add `/api/llm/mesh`.
- Embed `norllama_mesh` into `/api/llm/status`.
- Embed mesh state into `/api/v1/console-runtime/capabilities`.
- Teach the TUI local-LLM health probe to attach best-effort mesh summaries from
  `/v1/overview` or `/api/llm/mesh`.
- Carry `local_mesh` into local-first route decisions so route receipts can show
  why a local model was accepted.
- Treat internal `.home.arpa`/private HTTPS Norllama probes as local trust
  paths while keeping public HTTPS verification enabled.
- Update Norman live config to use `https://llm.home.arpa/v1` as the Norllama
  frontdoor and `gemma4:26b-a4b-it-q4_K_M` as the default offline model.

## Verification

- `make format`
- `make lint`
- `make test`
- Focused Norman remote suite: `41 passed, 4 warnings`.
- Full local test suite: `917 passed, 34 warnings`.
- Live Norman mesh snapshot: frontdoor `ok`, workers `3/3` healthy.
- TUI rollout: Norman, toy-box, and networking-host report `UI v2026.07.06.2`.
