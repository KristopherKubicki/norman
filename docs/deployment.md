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

- Python 3.14
- `uv` for managed Python and locked dependency installation
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

3. Install the release's declared Python line:

   ```
   uv python install
   ```

4. Create the locked virtual environment:

   ```
   uv sync --locked --no-dev
   ```

5. Activate it when running commands manually:

   ```
   source .venv/bin/activate
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
curl -fsS http://127.0.0.1:18000/openapi.json
sudo systemctl stop norman-release@<release-sha>
```

Each new release must contain a standard `.venv` created from the repository's
`.python-version` with `uv sync --locked --no-dev` and the managed
configuration environment before starting this unit.
`norman-release-python` accepts exactly one legacy versioned virtualenv only
so an already-deployed release can remain a rollback target; new releases must
not create versioned virtualenv directories.

### Production Credential Wrapper

Use `scripts/systemd/norman-production@.service` and
`scripts/systemd/norman-production-launch` for a SHA-pinned production release.
Install the launcher at `/usr/local/libexec/norman-production-launch` with mode
`0755`, and install the unit at
`/etc/systemd/system/norman-production@.service`. The unit is deliberately
separate from the loopback canary and from the legacy `norman.service`.
Install the release interpreter resolver as well. It selects the release-local
`.venv` without encoding a Python version in the unit:

```bash
sudo install -D -m 0755 scripts/systemd/norman-release-python \
  /usr/local/libexec/norman-release-python
```

Install `scripts/tmpfiles.d/norman-production.conf` at
`/etc/tmpfiles.d/norman-production.conf` and apply it before starting the
production unit. It keeps the persistent SQLite state directory owned by the
production service user:

```bash
sudo install -D -m 0644 scripts/tmpfiles.d/norman-production.conf \
  /etc/tmpfiles.d/norman-production.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/norman-production.conf
```

The compiled Norllama route-policy artifact is owned by the production service
user. The tmpfiles rules normalize ownership during upgrades, and
`norman-production@.service` refreshes it before the API starts, so the facade
never starts with a policy version that does not match its deployed runtime.
Install the periodic refresh service and timer as well:

```bash
sudo install -D -m 0755 scripts/systemd/norman-refresh-active-route-policy \
  /usr/local/libexec/norman-refresh-active-route-policy
sudo install -D -m 0644 scripts/systemd/norman-route-policy-refresh.service \
  /etc/systemd/system/norman-route-policy-refresh.service
sudo install -D -m 0644 scripts/systemd/norman-route-policy-refresh.timer \
  /etc/systemd/system/norman-route-policy-refresh.timer
sudo systemctl daemon-reload
sudo systemctl enable --now norman-route-policy-refresh.timer
```

The loopback `norman-release@.service` canary writes a separate policy under
`/run/norman-release-<release-sha>/` and resolves its runtime service tokens
through the same encrypted credential wrapper as production. It cannot replace
the policy used by the active production facade.

### Norllama Fleet Operations

Install the Norllama worker policy and health timers on the controller. The
policy refresh generates one route-policy artifact, validates it on the Mac
mini and both Spark workers, and promotes it without restarting a worker.
Health state is written in the format consumed by the existing Switchboard
alert policy.

```bash
for unit in \
  norllama-fleet-policy-refresh.service \
  norllama-fleet-policy-refresh.timer \
  norllama-fleet-health.service \
  norllama-fleet-health.timer \
  norllama-fleet-alerts.service \
  norllama-fleet-alerts.path \
  norllama-fleet-policy-refresh-alerts.service \
  norllama-fleet-policy-refresh-alerts.path; do
  sudo install -D -m 0644 "scripts/systemd/$unit" "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl enable --now \
  norllama-fleet-policy-refresh.timer \
  norllama-fleet-health.timer \
  norllama-fleet-alerts.path \
  norllama-fleet-policy-refresh-alerts.path
```

The alert path activates only when `/etc/norman/tui-fleet-alerts.env` is
configured. Run a non-disruptive ASR redundancy drill with:

```bash
python3 scripts/norllama/asr_failover_drill.py
```

It verifies both Spark ASR backends and the Mac gateway's multi-backend
readiness without replaying an audio upload.

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

### Explicit Bedrock Mantle fallback

The explicitly selected `gpt-5.6-*` Bedrock Mantle fallback uses a separate
broker from the generic Norman Keys resolver. It accepts only the public-facing
logical alias `networking/bedrock-mantle`, reads
`norman/bedrock-fallback` through the encrypted systemd credential, and mints
a fresh bearer token in memory for each request. It never stores the bearer
token in a file, environment variable, configuration secret, or log.

After the release virtualenv has been installed, configure the managed
environment with the approved region and release-aware resolver:

```text
NORMAN_BEDROCK_MANTLE_REGION=us-east-2
NORMAN_BEDROCK_MANTLE_SECRET_CMD="/usr/local/libexec/norman-release-python --current --release-script scripts/norman_bedrock_mantle_broker.py get {name}"
```

Set `prompt_facade_explicit_cloud_mantle_api_key_secret:
networking/bedrock-mantle` in `norman/runtime-config`. Keep the fallback
disabled unless an explicitly approved cloud model is selected. The token
generator's stable API creates a fresh token with a 12-hour validity; it is
not cached or persisted by Norman. The production and candidate units set
`NORMAN_RELEASE_SHA` themselves, so this command always runs the broker from
the release serving the request.

The AWS credentials behind `norman/bedrock-fallback` should belong to a
dedicated runner identity. Grant that identity access only to the approved
Mantle project. Preview the policy before applying it:

```bash
python scripts/configure_bedrock_mantle_iam.py \
  --profile <admin-profile> \
  --user-name <dedicated-runner-user> \
  --region us-east-2 \
  --project default
```

Apply the same policy with `--apply`. The command writes an inline policy and
then uses IAM policy simulation to verify both
`bedrock-mantle:CreateInference` and
`bedrock-mantle:CallWithBearerToken`. Rotate the encrypted credential if its
access key belongs to a general-purpose or unrelated automation identity.

The legacy `norman.service` rollback path must use the same identity file.
Install `scripts/systemd/norman.service.d/10-runtime-env.conf` before removing
the legacy plaintext token file.

For each production deployment, confirm the unit resolves to the expected
release and that the front door and local model lane remain healthy:

```bash
systemctl is-active norman-production@<release-sha>
curl -fsS http://127.0.0.1:8000/openapi.json
curl -fsS https://norman.home.arpa/openapi.json
curl -fsS https://llm.home.arpa/v1/models
systemctl status norman-route-policy-refresh.timer
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
`~/.local/bin/codex`, `~/.local/bin/codex-work`, and
`~/.local/bin/codex-work-fast`. `codex-work` always uses its managed Codex
version with app connectors enabled; `codex-work-fast` is the explicit
no-apps variant. The installer ensures that local bin directory precedes the
NVM Codex binary in `.bashrc` and any existing
`.bash_profile`. Mapped checkouts fail closed if the wrong launcher or a
provider-changing override is supplied.

Every mapped TUI needs a matching logical Norman Keys alias:

```text
<route>/prompt-proxy-token
```

`norman` retains `norman/prompt-proxy-token`. The alias must resolve to the
bearer token accepted by that route's `/v1` gateway. Configure the user shell
or the proof service with an approved `NORMAN_SECRET_CMD` or leased
`NORMAN_KEYS_URL` resolver. Do not store a gateway bearer token in shell
startup files, Codex profiles, systemd environment files, or the checkout.
When neither resolver is configured, the helper fails closed and reports that
approved broker access is unavailable. Codex TUIs do not fall back to `cred`
or ask for a vault passphrase.

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

To catch broken Responses tool continuations before they strand a TUI session,
install the synthetic streaming canary. It makes three authenticated streaming
`/v1/responses` requests through `https://cp.kris.openbrand.com`, using only
synthetic tool-search and tool-result payloads. It never invokes a real MCP,
Codex App, or external service. The canary requires native function-call SSE
events, `response.completed`, and `[DONE]` on every turn, and fails if raw tool
JSON appears in output text. The unit uses the same approved resolver
configuration as the route proof when configured, otherwise its installed
local broker. It obtains only `control-plane/prompt-proxy-token` and writes a
sanitized receipt with response IDs, timings, tool names, counts, and
tool-chain status:

```bash
scripts/deploy_norman_tui_tool_chain_canary.sh
```

The installer requires noninteractive sudo, but no route-proof configuration
file. It never reads a secret into the shell. It starts one immediate check,
then enables the timer to run no more than once per hour. The canary skips the
check when the local host-pressure guard defers or blocks new work. Inspect the
latest result at
`$HOME/.local/state/norman/tui-tool-chain-canary.json`; it deliberately omits
prompts, response text, arguments, tool output, tokens, and credentials.

### Codex Bridge Parity Evaluation

The Responses canary proves tool transport. It does not measure whether a
transparent Codex route performs comparably to a native Codex session on
repository work. Use the parity evaluator for that decision:

```bash
scripts/codex_bridge_parity.py \
  --workspace "$HOME/code/control_plane" \
  --live \
  --require-complete
```

It alternates direct native Codex and `codex-work` runs over five real,
read-only Control Plane policy and runbook tasks. Each run uses Codex
`read-only` sandboxing and an ephemeral session. The evaluation gates on
completion, contract score, unfinished future-work responses, and tool-event
continuity. It writes only sanitized metrics, answer hashes, and gate results
to `$HOME/.local/state/norman/codex-bridge-parity.{json,md}`; prompts, event
streams, and model answers remain in a temporary directory and are deleted
when the run ends.

Route homes expose only their relevant managed skills. For example, the
Control Plane route receives its Control Plane and Ops skills, not unrelated
work-route skill inventories.

Run it without `--live` to validate the task set and report plumbing without
calling either model route. Set `CODEX_REAL_BIN` or pass
`--native-codex-bin` if the direct Codex executable cannot be resolved
automatically. A `pass` is a promotion signal, not a substitute for the
hourly Responses tool-chain canary.

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

### Codex Session Pressure and History Retention

Long-lived `codex resume` sessions can load very large JSONL histories into a
single TUI process. When several are retained simultaneously, memory pages are
moved to swap and the TUI becomes sluggish even when the machine still reports
available RAM. The session guard prevents this failure mode without deleting or
terminating active work:

```bash
scripts/deploy_codex_session_guard.sh
```

The deployment installs a `codex-work resume` guard, an every-15-minute
session-pressure report, and a daily retention job. The report is written to:

```text
~/.local/state/norman/codex-session-pressure.json
~/.local/state/norman/codex-session-prune.json
```

Direct `codex-work resume --last` and `codex-work resume <session-id>` calls
are blocked when their JSONL exceeds the configured 512 MiB limit or a bounded
tail scan finds a high-confidence runaway pattern. The default runaway stops
are three recent compactions or three identical non-polling tool calls with
identical arguments. Passive status polls and overall tool-call density are
reported as warnings, not automatic stops.
Bare `codex-work resume` still opens Codex's native picker, so it warns instead
of trying to filter the picker. The deliberate escape hatch is:

```bash
CODEX_WORK_ALLOW_OVERSIZE_RESUME=1 codex-work resume <session-id>
```

Do not use the override as a normal workflow. Preserve a concise handoff in
the worktree or BBS, exit the oversized session normally, and start a fresh
session. The pressure monitor reports active PID PSS, SwapPss, compaction
churn, exact tool-call repetition, and bounded token snapshots. It never
records tool arguments in the report and never signals, terminates, or deletes
an active session.

New `codex-work` sessions and both Norman TUI launchers also export
`PYTEST_XDIST_AUTO_NUM_WORKERS=4`. pytest-xdist honors that variable only for
`pytest -n auto`, preventing an agent test run from claiming every CPU on the
interactive host. Deliberate capacity-test overrides are available per entry
point:

```bash
CODEX_WORK_PYTEST_XDIST_AUTO_WORKERS=8 codex-work
NORMAN_CODEX_PYTEST_XDIST_AUTO_WORKERS=8 scripts/norman_codex_launch.sh
```

Prefer a bounded worker count or the normal test command when the local host
pressure report is not healthy.

The pruning job keeps the 20 newest session files per Codex home and removes
only files older than 14 days. Before deletion it inspects open file
descriptors and skips every active JSONL, including one held by a process other
than Codex. It replaces the former date-directory-only pruning job.

The existing local host pressure guard now treats sustained 95%+ swap use as a
failure and defers background work. It remains non-destructive. Once active
oversized sessions have been handed off and closed, stale swap can be cleared
without a reboot:

```bash
sudo swapoff -a
sudo swapon -a
free -h
swapon --show
cat /proc/pressure/io
```

BBS posting is intentionally disabled until an approved BBS-scoped secret
broker is configured. Install a non-secret
`/etc/norman/tui-fleet-alerts.env` based on
`scripts/systemd/norman-tui-fleet-alerts.env.example`; the broker must resolve
the logical alias `bbs.norman.post-token`. Do not point it at the Codex gateway
broker, whose policy deliberately permits only `*/prompt-proxy-token` aliases.
Without this configuration the alert services are skipped cleanly rather than
failing repeatedly.

### Norman Codex Terra Contract

`codex-work` launches `openai.gpt-5.6-terra` through the Norman Responses
facade. The facade preserves the TUI bridge, route receipts, and tool protocol;
it does not select a local coding model or make a server-owned local fallback.

Before an interactive session starts, the launcher obtains one brokered gateway
token and verifies that `/v1/models` accepts it and advertises the Terra model.
`codex --verify` performs that same non-invoking check. `login`, `logout`,
`--help`, and `--version` remain available without a gateway check.

The API still exposes local-model aliases and `/v1/norman/capacity` for
non-TUI compatibility and local-operations diagnostics. They are not valid
`codex-work` selections and must not be used as a fallback for a Terra session.
If Terra cannot be reached, the TUI fails explicitly and the route receipt
records the effective provider, model, bridge mode, and failure reason.

The pre-TUI output may show locally captured subscription capacity windows and
the current calendar-month metered estimate when those state files are
available. Those are local usage data, not a provider-reported billing balance
or invoice. `NORMAN_CODEX_STATE_DIR`, `NORMAN_CODEX_USAGE_PATH`,
`NORMAN_CODEX_USAGE_LEDGER_PATH`, and `NORMAN_CODEX_ACCOUNT_CAPACITY_PATH`
provide explicit read-only diagnostic overrides.

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
   source .venv/bin/activate
   ```

3. Pull the latest changes from the repository:

   ```
   git pull
   ```

4. Refresh the declared Python and locked packages:

   ```
   uv python install
   uv sync --locked --no-dev
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

## Gateway outages and local rescue

Generic `codex-work` uses `https://norman.home.arpa/work/v1`, an explicit
**work model route** on Norman CT241. Its trusted gateway identity is `work`;
it does not depend on Keystone's hostname or application identity. Keystone
checkouts retain their own `compere` route. Other mapped checkouts also retain
their application routes. Never replace a work route with Norman's personal
`/v1` route to bypass an outage.

Before switching clients, register `gateway_routes.work = "work"` in the
server-owned AWS account registry, verify the `work` binding's owner and allowed
regions, and enable `work` in the backend route allowlist. The registry is read
on each binding check and unknown routes fail closed when account routing is
required. Preserve all existing bindings. The Caddy `/work/*` handler uses an
explicit client allowlist, strips the prefix, and overwrites the route header;
it exposes only model API and status handlers, not application pages. On an
existing host, preserve its current work client allowlist during migration.

`scripts/codex_work_gateway.py` atomically updates just the generic work
provider's transport/auth fields. It preserves the selected model, MCP settings
and session history. Run it after any older profile generator until that
runtime generator has been reconciled. The gateway currently uses one shared
brokered bearer credential (`norman/prompt-proxy-token`); route aliases are not
independent credentials. The trusted front door and server account registry
establish ownership. This migration does not claim credential isolation or a
second backend. The backend's Responses continuation cache remains in memory;
restarts can lose `previous_response_id` state even when local history survives.

Caddy serves `/_gateway/status` (and `/work/_gateway/status`) from a small watchdog receipt independently of
the Python API. It reports `ready`, `recovering`, `restarting`, `recovery_stalled`,
`restart_requested`, `unavailable`, or `maintenance`, with a timestamp, outage
age and suggested polling interval. `ready` means backend HTTP health only;
model readiness is separate. Clients reject receipts older than 45 seconds.
A host/network failure can make the status endpoint unreachable too; that is
unknown readiness, never an optimistic healthy result.

Install `scripts/deploy_gateway_watchdog.sh` **on Norman**. Its ten-second timer
records phase changes in the journal and atomically updates
`/var/lib/norman/gateway-health/status.json`. Existing systemd `Restart=always`
handles process exits. The watchdog additionally allows one `try-restart` only
when the sole enabled, running production unit has returned no HTTP response
for at least 180 seconds and has itself been running for 180 seconds. It never
restarts for an HTTP error, a cloud/model failure, an intentionally stopped
service, an ambiguous unit selection, or an active deployment transition.
Recovery attempts have a fifteen-minute cooldown and a maximum of two per hour.
A failed restart request consumes that budget. A persistent failure requires an
operator; neither the watchdog nor the model may repeatedly bounce the service.

For deliberate maintenance, create `/run/norman-gateway-maintenance.json` as
root with `{"until": <future Unix timestamp>}` before changing the backend.
Remove it after verification. An invalid marker suspends automatic recovery
until corrected. This does not stop systemd's own restart policy.

New routed sessions check the independent status and visibly wait up to 120
seconds. They stop before launching if readiness does not return; history is
preserved. Existing sessions benefit from Caddy's refused-connection wait.
After an exhausted refused dial, Caddy returns structured HTTP 503 with
`Retry-After: 10` and the status URL. It does not replay a POST already accepted
by the backend. It cannot guarantee continuity after an interrupted response.

Operator commands installed by `scripts/install_codex_route.sh`:

```sh
codex-gateway-status
codex-gateway-status --endpoint https://cp.kris.openbrand.com/v1 --wait 120
codex-rescue --scope work --check
codex-rescue --scope personal --check
codex-rescue --scope work --prompt 'Backend TCP connections are refused during startup; suggest read-only checks.'
codex-rescue --scope personal --prompt 'Summarize these personal-service outage observations.'
```

Rescue talks directly to the owning Spark's Norllama gateway (work
`192.168.42.151:18151`, personal `192.168.40.150:18151`), so it works independently
of Norman, Keystone, their token broker, and cloud providers. It checks signed
policy readiness and actual model residency, selects an advertised worker-local Qwen model, disables peer
spillover, disables HTTP proxies/redirects, limits input/output/time, and sends
no tools. It reads only explicitly supplied text, not session history or logs.
Model suggestions are untrusted advisory output; they cannot restart services,
change billing routes, execute repairs or resume a cloud conversation. A local
worker or policy failure is reported rather than bypassed. Keep scope explicit.
`--check` performs only readiness/catalog/residency reads: it does not read stdin,
send a prompt, generate a completion or inspect history. A cold model is reported
unavailable instead of triggering an implicit load during an outage. The catalog
may advertise loopback or the selected worker's own LAN address; another worker's
address is rejected, including catalogs mixing local and cross-owner hosts.

Networking VM232 remains the owner of Norllama fleet checks and recovery drills;
do not reactivate migrated HAL copies. Worker readiness is not proof of successful
inference, so verify a bounded completion as well. Fleet peer failover is not a
replacement for a second Norman Responses backend. Health-gated production
cutovers, draining in-flight requests, and compatible shared continuation state
are still needed before claiming redundant gateway failover.

The separate `norman-gateway-observer.timer` belongs on Networking VM232. It
polls the independent status every thirty seconds and keeps
`~/.local/state/norman/gateway-observer.json`, so a Norman host failure is still
observed. After three minutes unavailable it may request one bounded, tool-free
Qwen diagnosis on the work worker, no more than once per fifteen minutes. Only
phase, HTTP code and outage duration are supplied; transcripts and remote status
messages are excluded. Advice is explicitly advisory and dated, with no restart,
notification or model-routing authority. It remains inspectable even when
Norman is down. It does not send Slack, email or SMS notifications.

Use `scripts/deploy_gateway_observer.sh` on Networking to install the observer;
its status probe targets `https://norman.home.arpa/_gateway/status`, independently
of work-application access lists. For rollback, stop the corresponding timer
first (`norman-gateway-watchdog.timer` on Norman or
`norman-gateway-observer.timer` on Networking); stopping either timer does not
stop the production API. Restore the recorded Caddy/configuration and launcher
backups and validate before reloading. Preserve session files and watchdog
attempt history. Operational receipts for the October 7 installation are under
`~/.local/state/norman/gateway-outage-recovery-20261007` on Norman and
`/var/lib/networking/gateway-outage-recovery-20261007` on Networking.


Recovery receipts are also action budgets. Missing state permits first startup;
malformed or unreadable state suspends automatic restarts and automatic local
advice, with `recovery_state_invalid: true`. Health observations continue, including
reporting a genuinely healthy backend as ready. The invalid-state flag survives
subsequent writes and healthy periods. Preserve and inspect the damaged receipt,
then restore a verified receipt or reconcile the previous action timestamps before
clearing the flag; deleting the file is not a safe way to reset a spent budget.
Non-finite, negative, boolean and nonnumeric timestamps are invalid. Valid future
action timestamps remain in the budget so clock rollback cannot unlock retries.

Scheduled and manual runs lock the same state file before reading it. Overlapping
runs exit without observing or acting. Receipt writes use unique temporary files,
flush file and directory metadata, and atomically replace the live receipt before
an automatic action. A failed write stops the action. These locks supplement
systemd's single-instance scheduling and do not restart the application itself.


The status client connects directly to the configured front door, without
following redirects or consulting HTTP proxy environment variables. Invalid
endpoints (including embedded credentials, bad ports and control characters)
stop preflight immediately. Malformed profiles fail with an actionable message.
A receipt must be bounded, fresh, use a known recovery phase, contain a printable
message and report a valid backend HTTP code; `ready` requires backend HTTP 200.
Contradictory or malformed receipts are unavailable, never optimistic readiness.
These checks describe backend health; model readiness remains a separate probe.

HAL's default status command probes the `/work` front door and its work-client
access rules. Networking's scheduled observer explicitly probes
`https://norman.home.arpa/v1`; use that same `--endpoint` for manual checks there.
An HTTP 403 on the work route from Networking means access is denied, not that
the backend is down. Keep those access rules intact when diagnosing recovery.

Interactive `codex` and `codex-work` launches keep a small terminal supervisor
outside router re-entry. It restores the original terminal attributes and disables
mouse/focus reporting, bracketed paste and alternate-screen mode after the client
exits, then makes the cursor visible. This limits raw mouse escape sequences leaking
into the shell after an abnormal client exit. It preserves exit status, leaves the
child in the foreground job's process group, and propagates child-only suspension
so shell suspend/resume still works. Ctrl-C is not forwarded twice to the client.

The supervisor never reads or flushes terminal input, copies transcripts, resumes
sessions or retries requests. Piped/non-TTY commands execute directly, preserving
machine-readable output. Install `scripts/codex_terminal_guard.py` with the launcher
installer; narrowly updating existing wrappers preserves their local routing changes.
It applies to new launches only. Killing the supervisor itself with SIGKILL, a host
failure or a closed terminal can prevent cleanup. Already queued mouse bytes may
remain because discarding input could also discard the user's keystrokes. This is
terminal recovery, not a fix for interrupted inference or durable Responses state.

### Connector account verification

Model routing and connector authentication are separate. Selecting the work
model gateway does not switch Gmail, Calendar, Contacts, Jira, or another
connected app's OAuth identity. `codex-work` disables connected apps by default;
`--work-apps` explicitly enables them but does not select or verify an account.
Custom MCP servers have their own credentials and remain independently scoped.
The installed work launcher already uses this default; the source wrapper now
preserves it on reinstall.

Generated route instructions require a read-only identity check before the
first account-specific operation, and again after reconnecting or changing
ownership. Verify each Google connector's profile independently. For Jira,
verify the current user, site/cloud ID, and intended project. Unknown or wrong
identity blocks that connector operation without stopping unrelated work.
Instructions guide agent behavior; they are not a server-side authorization
boundary or automatic OAuth switching. Existing running sessions need these
instructions explicitly or a new launch.

The October 8 HAL audit verified the current injected Gmail, Calendar, and
Contacts tools against the same personal account. The Atlassian plugin was
available but not connected in that tool surface. Work homes separately
registered Ops Portal and Scout MCP servers; configuration is not evidence of
live connector identity or Jira access. No mailbox contents were read and no
messages or tickets were changed. Connecting a work Google account or Atlassian
requires its own authenticated connection; never recover by borrowing the
personal connection or exposing broker credentials.

The optional local file `~/.config/norman/codex-connector-accounts.json` records
public Google identity expectations, not credentials or authenticated receipts:

```json
{
  "schema_version": 1,
  "google": {
    "work": "operator@example.com",
    "personal": "operator@gmail.com"
  }
}
```

Both distinct identities are required. Missing, malformed, oversized, or
unreadable policy produces no usable expected identity; generated instructions
block Google account-data operations until identity is established while
allowing profile checks and independent work. The router refreshes these
expectations in managed session instructions and reports them under
`connector_accounts` in `--print-route`. Its `authenticated_identity_verified`
and `automatic_account_switching` remain false: a local file cannot certify a
remote OAuth session. Each Google connector must independently return the
expected profile. Personal mail containing work messages is not a work-account
fallback. Jira retains separate current-user/site/project verification.

Only an explicit leading `--work-apps` opts the source wrapper into apps. An
inherited `CODEX_WORK_DISABLE_APPS=0` cannot enable apps for a child work session.
The explicit choice survives both router and credential-launcher re-entry. The
installed HAL wrapper already ignores that ambient variable; preserve its
other runtime fixes when backporting this change.

Unmapped work sessions and work management commands re-enter `codex-work` and
retain the work home. A missing work launcher is an error; it must not fall
through to regular/personal Codex. This also preserves the work boundary for
`login`, `mcp`, and `resume` outside a mapped checkout. HAL already used this
work fallback; the source router now does too.

Codex home selection rejects known opposite-owner directories before launch or
profile writes. This covers generic `.codex`/`.codex-work`, named route homes,
an explicitly configured work home inherited by regular Codex, child paths,
and symlink aliases. Resolution failures stop the launch. The check reads path
metadata only; it never reads authentication files. Correct `CODEX_HOME` or
`CODEX_WORK_HOME`, or use the matching launcher when rejected. An unknown custom
home is not proven to belong to either owner; this is a guard against known
cross-owner selection, not a complete classification or OAuth isolation system.
Personal launches also discard the inherited work Ops MCP bearer variable and
binding-loaded marker from the child environment, preserving the parent and
work launches. Existing running processes are unchanged.

The boundary audit (`tests/test_codex_boundary_audit.py`) checks all named-home
owner pairs and all recognized-origin/directory-name pairs. Recognized Git
origin wins before any folder-name fallback; a renamed clone must not change
its owner because an earlier route matches the folder. Real temporary Git
repositories also prove mismatched launchers are rejected before execution or
credential lookup.

Routing parses attached short options as well as long/value forms, skips option
values, and respects `--` as the end of options. Literal prompt text cannot
select a checkout, impersonate help, change a model/profile, or toggle apps.
Duplicate or empty `-C`/`--cd` is rejected before routing. Work wrapper switches
are consumed only as switches, preserving literal prompts and option values.
The audit can target an installed router/wrapper using `CODEX_AUDIT_ROUTER_PATH`
and `CODEX_AUDIT_WORK_WRAPPER`; its isolated homes and stubbed executors never
send messages, mutate tickets, retrieve credentials, or launch model sessions.

Local Codex help and version requests now bypass session preparation, gateway
preflight, and optional Ops MCP credential loading. They still validate the
launcher's Codex home against known opposite-owner homes and preserve the pinned
work CLI selection. Argument values and literal prompts after `--` cannot trigger
this shortcut. This does not change authentication requirements for sessions or
connector management. The boundary audit also exercises both work wrapper paths
with a deliberately failing fake credential loader, asserting that it is never
called and no work profile directory is created for local CLI information.

The work shell launcher's help scanner also respects option values and the `--`
separator. Resume pressure checks and gateway preflight use this same scanner, so
literal `--help`/`-h` prompt text cannot skip startup checks. Regression tests run
the actual shell functions against a fake pressure guard and check every
value-taking option declared by the router for scanner consistency.

Work profile selection now stops at `--` and consumes unrelated option values
before interpreting profile flags. Attached `-p=work` selects the same profile as
`-p work`; empty or missing names fail explicitly. Resume-target discovery also
consumes `--profile-v2`, `--color`, and output-file/schema options, preventing their
values from being checked as session IDs. These are CLI parsing rules, not proof
of any connector's authenticated identity.
