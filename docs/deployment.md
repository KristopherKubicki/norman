# Deployment

This document outlines the steps to deploy Norman on a server or cloud provider. The guide covers installation,
configuration, and basic maintenance tasks.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Updating Norman](#updating-norman)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before deploying Norman, ensure that your server meets the following requirements:

- Python 3.8, 3.9, 3.10, or 3.11
- SQLite (or another supported database system)
- A compatible operating system, such as Ubuntu, Debian, or CentOS

## Installation

1. Clone the Norman repository:

   ```
   git clone https://github.com/KristopherKubicki/norman.git
   ```

2. Change to the Norman directory:

   ```
   cd norman
   ```

3. Create a virtual environment:

   ```
   python3 -m venv env
   ```

4. Activate the virtual environment:

   ```
   source env/bin/activate
   ```

5. Install the required packages:

   ```
   pip install -r requirements.txt
   ```

## Configuration

1. Run Norman once to automatically create `config.yaml` with secure defaults.
   Edit this file to configure the required settings, such as the database connection string and API keys.

### Managed Service Configuration

Production services should not generate or keep `config.yaml` in a release
checkout. Set `NORMAN_CONFIG_SECRET` to a logical Norman Keys name and provide
one approved resolver:

```text
NORMAN_CONFIG_SECRET=norman/runtime-config
NORMAN_CONFIG_SECRET_CMD=<approved broker command using {name}>
NORMAN_CONFIG_REQUESTER_ID=norman-release
NORMAN_CONFIG_TARGET_HOST=norman.lollie.org
```

`NORMAN_CONFIG_SECRET_CMD` is preferred for the temporary machine-local `cred`
vault bridge. An external Norman Keys endpoint can instead be configured with
`NORMAN_KEYS_URL` and its short-lived service token. The secret value must be
a YAML mapping containing the normal `config.yaml` overrides, including a real
`admin_setup_key`.

Norman fails closed when a configured secret cannot be read or has invalid
YAML. It does not log the returned contents, generate a replacement
`config.yaml`, or silently fall back to a repo-local config file. The optional
`NORMAN_CONFIG_PATH` migration setting must be an absolute path outside the
application working tree; do not use it to point back at a release checkout.
When the secret policy has `allowed_hosts`, set
`NORMAN_CONFIG_TARGET_HOST` to the exact approved hostname. Hostname matching
is case-insensitive and ignores a trailing dot; an unset or unapproved host is
denied.

The repository includes `scripts/systemd/norman-release@.service` for a
loopback-only canary. It is intentionally separate from `norman.service`, so a
candidate can be validated without replacing the active service:

The canary reads its resolver settings only from `/etc/norman/release.env`;
do not reuse the live service's `/etc/norman/runtime.env`. Keep
`release.env` root-owned and mode `0600`, and limit it to
`NORMAN_CONFIG_SECRET` plus the selected broker resolver and token settings.

```bash
sudo systemctl daemon-reload
sudo systemctl start norman-release@<release-sha>
curl -fsS http://127.0.0.1:18000/health
sudo systemctl stop norman-release@<release-sha>
```

The release checkout must contain `.venv-3.10` and the managed configuration
environment before starting this unit.

### Production Credential Wrapper

Use `scripts/systemd/norman-production@.service` and
`scripts/systemd/norman-production-launch` for a SHA-pinned production release.
Install the launcher at `/usr/local/libexec/norman-production-launch` with mode
`0755`, and install the unit at
`/etc/systemd/system/norman-production@.service`. The unit is deliberately
separate from the loopback canary and from the legacy `norman.service`.
Install `scripts/tmpfiles.d/norman-production.conf` at
`/etc/tmpfiles.d/norman-production.conf` and apply it before starting the
production unit. It keeps the persistent SQLite state directory owned by the
production service user:

```bash
sudo install -D -m 0644 scripts/tmpfiles.d/norman-production.conf \
  /etc/tmpfiles.d/norman-production.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/norman-production.conf
```

The unit reads only non-secret identities from
`/etc/norman/runtime-identities.env`. Store the following logical aliases in
the approved Norman Keys resolver or the encrypted `cred` migration vault:

```text
norman/prompt-proxy-token
norman/console-runtime-service-token
norman/keys-service-token
```

The unit loads a systemd encrypted credential containing the vault passphrase
and the launcher resolves the aliases only into the child process. Do not add
the token values to an environment file, a unit drop-in, a release checkout,
or shell history. The machine-local `cred` bridge is a migration fallback;
move these aliases to a networked Norman Keys backend with short-lived leases
when that backend is available.

The legacy `norman.service` rollback path must use the same identity file.
Install `scripts/systemd/norman.service.d/10-runtime-env.conf` before removing
the legacy plaintext token file.

For each production deployment, confirm the unit resolves to the expected
release and that the front door and local model lane remain healthy:

```bash
systemctl is-active norman-production@<release-sha>
curl -fsS http://127.0.0.1:8000/health
curl -fsS https://norman.home.arpa/health
curl -fsS https://llm.home.arpa/v1/models
```

To roll back a bad production release, stop and disable the SHA-specific unit,
then re-enable and start the prior known-good unit. Keep the legacy service
disabled unless it is the intentionally selected rollback target:

```bash
sudo systemctl stop norman-production@<bad-sha>
sudo systemctl disable norman-production@<bad-sha>
sudo systemctl enable --now norman-production@<known-good-sha>
```

### Codex TUI Route Deployment

Install the checkout-aware `codex` and `codex-work` wrappers from the Norman
checkout:

```bash
scripts/install_codex_route.sh
exec "$SHELL" -l
```

The installer copies the router and token helper to
`~/.local/lib/norman-codex-route`, installs the wrappers at
`~/.local/bin/codex` and `~/.local/bin/codex-work`, and ensures that local bin
directory precedes the NVM Codex binary. Mapped checkouts fail closed if the
wrong launcher or a provider-changing override is supplied.

Every mapped TUI needs a matching logical Norman Keys alias:

```text
<route>/prompt-proxy-token
```

`norman` retains `norman/prompt-proxy-token`. The alias must resolve to the
bearer token accepted by that route's `/v1` gateway. Configure the user shell
or the proof service with an approved `NORMAN_SECRET_CMD` or leased
`NORMAN_KEYS_URL` resolver. Do not store a gateway bearer token in shell
startup files, Codex profiles, systemd environment files, or the checkout.
When neither resolver is configured, the helper automatically uses the
machine-local encrypted `~/.local/bin/cred` vault when available. This fallback
also needs those logical aliases and is only intended during the Norman Keys
migration.

After broker provisioning, prove every route without sending a prompt:

```bash
scripts/codex_route_proof.py \
  --output-json "$HOME/.local/state/norman/codex-route-proof.json"
```

To monitor the CLI-to-gateway boundary, install the proof units and provide
only the non-secret broker command configuration in
`/etc/norman/codex-route-proof.env`:

```bash
sudo install -D -m 0644 scripts/systemd/norman-codex-route-proof.service \
  /etc/systemd/system/norman-codex-route-proof.service
sudo install -D -m 0644 scripts/systemd/norman-codex-route-proof.timer \
  /etc/systemd/system/norman-codex-route-proof.timer
sudo systemctl daemon-reload
sudo systemctl enable --now norman-codex-route-proof.timer
```

### Temporary Workspace Cleanup

Agent tasks can create large disposable worktrees, browser profiles, archives,
and test databases in `/tmp`. Install the cleanup units to remove only the
known generated paths after their retention period. The cleanup keeps unknown
temporary data, skips paths with open files, and preserves Git worktrees with
uncommitted changes.

```bash
sudo install -D -m 0644 scripts/systemd/norman-tui-tmp-workspace-cleanup.service \
  /etc/systemd/system/norman-tui-tmp-workspace-cleanup.service
sudo install -D -m 0644 scripts/systemd/norman-tui-tmp-workspace-cleanup.timer \
  /etc/systemd/system/norman-tui-tmp-workspace-cleanup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now norman-tui-tmp-workspace-cleanup.timer
```

The service cleans generated Norman test databases after 24 hours and known
agent workspace/artifact prefixes after 48 hours. Its most recent manifest is
written to `/var/lib/norman/state/tui-tmp-workspace-cleanup.json`.

### Local Host Pressure Guard

Install the local guard when Codex TUIs share a host. It samples I/O pressure,
memory and swap usage, root filesystem headroom, and Codex-related I/O every
15 seconds. It writes a local KPI report and posts deduplicated warnings or
automatic-pause notices to the Switchboard BBS.

```bash
sudo install -D -m 0644 \
  scripts/systemd/norman-tui-local-host-pressure-guard.service \
  /etc/systemd/system/norman-tui-local-host-pressure-guard.service
sudo install -D -m 0644 \
  scripts/systemd/norman-tui-local-host-pressure-guard.timer \
  /etc/systemd/system/norman-tui-local-host-pressure-guard.timer
sudo install -D -m 0644 \
  scripts/systemd/norman-tui-local-host-pressure-alerts.service \
  /etc/systemd/system/norman-tui-local-host-pressure-alerts.service
sudo install -D -m 0644 \
  scripts/systemd/norman-tui-local-host-pressure-alerts.path \
  /etc/systemd/system/norman-tui-local-host-pressure-alerts.path
sudo systemctl daemon-reload
sudo systemctl enable --now norman-tui-local-host-pressure-guard.timer
sudo systemctl enable --now norman-tui-local-host-pressure-alerts.path
```

The guard does not stop ordinary tests, browser activity, or unknown high-I/O
processes; it reports and alerts on them for human review. Automatic
intervention requires two consecutive samples with
`io.full avg10 >= 10`, a read rate of at least 100 MiB/s, and a live Codex
ancestor running `find` or `rg` against `/`, `/home`, `/home/kristopher`,
`/tmp`, or `/var/tmp`. It first sends `SIGINT` to the scan and then `SIGSTOP`
to the verified Codex process. PID start times are checked before either
signal, and the guard never kills a session automatically.

The current report is
`/home/kristopher/.local/state/norman/tui-local-host-pressure-guard.json`;
sampling state, including the most recent automatic actions, is in
`/home/kristopher/.local/state/norman/tui-local-host-pressure-guard-state.json`.
The report includes the exact evidence, the Codex PID, and both human controls:

```bash
kill -CONT -- <codex-pid>  # Resume the paused session
kill -TERM -- <codex-pid>  # Cancel the paused session
```

Review the report before resuming work. The BBS alert is a notification and
audit trail; the human decides whether to resume, cancel, or investigate.

### Norman Codex Capacity Contract

Every mapped Codex route is local-only for `norman-code`. Before an interactive
session starts, the launcher obtains one brokered gateway token and checks:

1. `/v1/models` accepts that token.
2. `/v1/norman/capacity?model=norman-code` reports a reachable Spark that
   advertises the coding model.

The capacity endpoint performs only a fresh mesh probe; it does not send a
prompt, load a model, or create model residency. The route starts only if the
endpoint reports `available: true` and `cloud_fallback: false`. A failed
preflight exits before Codex starts with a specific message such as:

```text
codex-route: norman session not started: local coding capacity is unavailable
(no_eligible_worker_reachable); retry later
```

This avoids presenting a local Spark outage as a generic hosted-model
high-demand condition. `codex --verify` checks the same two endpoints without
starting a TUI, including from Networking and the other routed checkouts.
`login`, `logout`, `--help`, and `--version` do not require capacity, so
recovery and diagnostics remain available while the model lane is down.

The API requires the normal route identity injected by Caddy and a valid
brokered bearer token. A successful capacity response is always HTTP 200; use
its `available`, `reason`, `retryable`, `eligible_workers`, `ineligible_workers`,
`frontdoor`, and `cache` fields to decide recovery. It intentionally treats
the Mac mini fallback node as ineligible for `norman-code`.

Local generation failures use the normal OpenAI-compatible error envelope and
always include `error.norman.cloud_fallback: false`. No local failure forwards
the prompt to a cloud model.

| Code | HTTP status | Meaning | Retry |
| --- | --- | --- | --- |
| `local_capacity_exhausted` | 503 | A worker reported no capacity. | Yes; respects `Retry-After`. |
| `local_capacity_unavailable` | 503 | The coding worker lane is unavailable. | Yes. |
| `local_model_unavailable` | 503 | No eligible worker has the coding model. | Yes after worker/model recovery. |
| `local_model_timeout` | 504 | A local model request exceeded its deadline. | Yes. |
| `local_gateway_unreachable` | 503 | Norman could not reach the local model gateway. | Yes. |
| `local_gateway_unavailable` | 503 | The local gateway returned an upstream 5xx failure. | Yes. |
| `local_gateway_auth_failed` | 503 | Gateway credentials are invalid or expired. | No; repair credentials. |
| `local_gateway_bad_response` | 502 | The gateway response is invalid. | Usually no for HTTP 4xx; inspect logs. |
| `empty_local_response` | 502 | The local model completed with no usable text. | Yes. |
| `local_model_not_installed` | 422 | The selected model is not installed. | No; deploy a supported model. |

The capacity endpoint can also return `unsupported_capacity_model` (400) for a
model alias outside the local catalog. Authentication and route-identity errors
remain explicit: `proxy_token_not_configured` (503), `invalid_api_key` (401),
and `gateway_route_*` (403).

Proxy events are persisted as JSONL at
`/var/lib/norman/state/proxy-events.jsonl` by default. The active log rotates
at 5 MiB into one prior generation, `proxy-events.jsonl.1`. Set
`NORMAN_PROXY_EVENT_LOG` to a different path, or set it to `0`, `false`, `none`,
`off`, or `disabled` to opt out. Set `NORMAN_PROXY_EVENT_LOG_MAX_BYTES` to
adjust rotation between 4 KiB and 100 MiB. The in-process dashboard and alerts
count local capacity failures, model timeouts, and gateway failures separately.

## Running the Application

Before starting a service, configure the deployment's database, authentication,
secret broker, and only the model or connector lanes it is approved to use.
Use `config.yaml.dist` as a starting point; do not put credentials in the
repository or rely on a default administrative account.

1. Activate the deployment's virtual environment.

2. Start the API service:

   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

3. Verify the service through its managed authentication path and the endpoints
   exposed at:

   - `http://<host>:8000/docs` for the OpenAPI UI
   - `http://<host>:8000/health` for a health check

The Console Runtime worker is disabled and dry-run by default. The Kaizen
broker is also disabled by default and starts with no model budget, target
edits, automatic actions, or notifications. Enable either only after their
service account, resource limits, policy, approval path, and rollback
procedure have been reviewed.

For the runtime and approval model, see the
[Architecture](architecture.md) and
[Norman Kernel Program](norman_kernel_program.md). For local-first route
selection, egress, fallback, and receipts, see
[Provider And Routing Resilience](llm_runtime_fallback.md).

## Updating Norman

To update your Norman installation, perform the following steps:

1. Stop the running Norman application.

2. Activate the virtual environment:

   ```
   source env/bin/activate
   ```

3. Pull the latest changes from the repository:

   ```
   git pull
   ```

4. Update the installed packages:

   ```
   pip install -r requirements.txt
   ```

5. Restart the Norman application.

## Troubleshooting

If you encounter issues during deployment or operation, consult the following resources:

- Norman's [GitHub Issues](https://github.com/KristopherKubicki/norman/issues) for known problems and solutions.
- The [FastAPI documentation](https://fastapi.tiangolo.com/) for general information on the web framework.
- The [Python logging documentation](https://docs.python.org/3/library/logging.html) for guidance on configuring and
  troubleshooting logging.
- Norman exposes a simple health check at `/health` that can be polled by monitoring systems.

Feel free to modify and expand this document to include any additional information or steps specific to your project or
deployment preferences.
