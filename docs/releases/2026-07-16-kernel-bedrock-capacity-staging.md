# Kernel Bedrock And Codex Capacity Staging

Date: 2026-07-16
Scope: Norman Kernel native Bedrock adapter, local-first routing, and Codex plan-capacity monitoring
Status: console fleet deployed; backend rollout staged pending a brokered-configuration canary

## Released Console Surface

The shared console fleet is on `UI v2026.07.16.07`. The fleet doctor reported 15
active consoles with no failures or warnings after the web-console rollout.

The console now:

- polls the Codex `/usage` surface only while its ChatGPT-authenticated terminal is idle;
- retains aggregate capacity, reset, and forecast data without retaining terminal contents;
- keeps ChatGPT plan, API, and Bedrock usage in separate ledgers;
- prefers direct Codex Flex over the default Bedrock lane only for fresh personal
  ChatGPT capacity above the configured reserve;
- rechecks ChatGPT auth before making that automatic route choice and removes an
  inherited `OPENAI_API_KEY` from ChatGPT-authenticated direct child processes.

No capacity probe runs while a prompt, worker, or unfinished terminal draft is active.
An unsupported `/usage` command is recorded as unavailable and retried only after a
long backoff.

## Backend Candidate

The staged backend adds a native AWS Bedrock Converse adapter for Norman Kernel.
It is selected only when an explicit policy route specifies Bedrock cloud proxy work.
Local, tool, and non-Bedrock routes continue to use Norllama.

The adapter:

- requires route-policy authorization before credential lookup;
- uses `boto3` and applies a bounded request timeout;
- obtains optional credentials through `NORMAN_KEYS_URL` or `NORMAN_SECRET_CMD`;
- records only broker source, secret name, lease, request, and expiry metadata;
- fails the selected Bedrock call instead of silently falling back to Codex or Norllama.

The source change requires the newly locked `boto3` dependency. Do not copy the
current dirty checkout to the Norman backend host.

## Managed Release Configuration

The clean release candidate must receive its settings through a brokered
`NORMAN_CONFIG_SECRET` and an approved command or HTTP resolver. On this path
Norman reads the YAML mapping in memory, does not create a release-local
`config.yaml`, and fails closed if `admin_setup_key` is missing.

`scripts/systemd/norman-release@.service` runs the release candidate only on
`127.0.0.1:18000` and requires both the logical config secret name and a
configured resolver before it starts. It is separate from the active
`norman.service`; use it for the clean loopback canary first.

The live host does not currently expose a confirmed brokered configuration
alias for this purpose. Leave `norman.service` on its existing healthy checkout
until that alias and resolver are provisioned. Do not copy its repo-local
config into the clean release checkout.

## Backend Rollout Gate

Create and push one clean release commit before backend deployment. Exclude generated
tmux profile data and unrelated local artifacts. The deployment source and the running
host must resolve to that exact commit.

Before restart, on the target host:

```bash
git fetch origin
git rev-parse HEAD
git show --stat --oneline <release-sha>
git status --short
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -c 'import boto3; print(boto3.__version__)'
./.venv/bin/alembic current
```

Use the repository's normal deployment mechanism to move the host to
`<release-sha>`. Run `alembic upgrade head` only after confirming that the selected
release includes a migration. This candidate does not introduce one.

Verify the production service environment has a brokered secret path before enabling
an AWS credential-secret route:

```text
NORMAN_KEYS_URL=<broker base URL>
NORMAN_KEYS_TOKEN=<short-lived broker token>
```

or:

```text
NORMAN_SECRET_CMD=<broker command with {name}>
```

Use a logical secret such as `networking/bedrock`; do not create a repo-local
plaintext credential file.

## Restart And Smoke

Restart only the backend service after the dependency and source checks succeed:

```bash
sudo systemctl restart norman.service
sudo systemctl is-active norman.service
curl -fsS http://127.0.0.1:8000/health
```

Then run the authenticated Console Runtime dry-run and route-policy rejection smokes.
They must show that a local route still uses Norllama and a serialized Bedrock route
without `allow_cloud_proxy` is blocked before any broker request.

After those pass, run one operator-approved Bedrock canary with an explicit
`provider=bedrock`, `cloud_proxy=true`, non-tool route and a bounded token/runtime
budget. Its durable model receipt must contain:

- `selected_provider: bedrock`;
- `usage_bucket: bedrock_amazon`;
- policy authorization success;
- broker metadata only, with no credential values.

Do not promote Bedrock as a default route from this canary. Keep Norllama local-first
and require an explicit cloud policy for every Bedrock turn.

## Rollback

Rollback is source-revision based:

1. Return the host to the prior known-good release commit.
2. Reinstall that revision's dependency set.
3. Restart `norman.service` and verify `/health`.
4. Set `allow_cloud_proxy=false` in the active route policy or disable the runtime
   worker until the issue is diagnosed.

The console fleet can remain on `2026.07.16.07`; its capacity monitor fails closed
when ChatGPT auth or fresh aggregate capacity is unavailable.

## Verification

Completed in the release workspace:

```text
make format
make lint
make test
./.venv/bin/pytest -q tests/test_agent_console_template_masking.py \
  tests/test_norman_codex_model_settings.py
./.venv/bin/pytest -q tests/test_tmux_api.py
```

Results before the tmux-profile isolation follow-up were `1899 passed, 6 warnings`.
The focused tmux profile test rerun completed `32 passed, 4 warnings` without mutating
the tracked profile pack. The managed configuration and bootstrap-log follow-up passed
`1904 passed, 6 warnings`; its focused configuration, app, and systemd checks passed
`18 passed, 5 warnings`.
