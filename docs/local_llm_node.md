# Local LLM Node

Recommended shape for the home offline model lane.

## Goal

Stand up one stable local inference endpoint for Norman and selected TUIs
without burning the larger 128 GB model workers on routine scout, filter,
summary, and fallback work.

## Hostname Plan

- primary local API host: `llm.[INTERNAL_DOMAIN]`
- site alias: `llm.knox.lollie.org`

`llm.[INTERNAL_DOMAIN]` is the preferred Norman local model front door. It
should serve Norllama directly through the Norman front door instead of
redirecting to another LLM hostname. `llm.knox.lollie.org` remains a site alias
for tailnet/road access and older clients.

## Runtime Plan

- run Ollama and Norllama natively on the Mac mini fallback node
- keep Ollama bound to loopback only, currently `127.0.0.1:11434`
- expose the TUI local lane and frontdoor API through the logical
  `https://llm.[INTERNAL_DOMAIN]` name
- terminate TLS on Norman's front door
- reverse proxy the LLM hostnames from Norman to the Norllama mesh, preferring
  2.133 and failing over to 2.150/2.151 when needed
- keep the Mac mini free of privileged ports unless it gets a dedicated sudo/root service path

Do not make Docker on macOS the primary path here. The point of the Mac mini is
Apple GPU acceleration, and the clean path is the native macOS runtime.

Current hardware roles:

- `192.168.2.133`: 16 GB fallback/front-door node for tiny local models.
  Installed fallback set is `llama3.2:3b`, `llama3.2:1b`, `gemma3:1b`,
  `gemma3:4b`, `qwen3:1.7b`, `qwen3:4b`, and `qwen3:8b`, but those are not
  the normal TUI text defaults.
- `192.168.2.150` and `192.168.2.151`: 128 GB large-model workers. They should
  run local systemd-managed Norllama gateways on `:18151`, with Ollama private
  on `127.0.0.1:11434`. Clients and TUIs should reach them through
  `llm.[INTERNAL_DOMAIN]`; direct worker addresses are backend/diagnostic
  addresses, not the normal client contract.

## Norman Front Door

The live front door is rendered by:

- `scripts/render_norman_bot_proxy_caddy.py --mode hosts`

It produces:

- `http://llm.[INTERNAL_DOMAIN]` -> `https://llm.[INTERNAL_DOMAIN]`
- `http://llm.knox.lollie.org` -> `https://llm.knox.lollie.org`
- `https://llm.[INTERNAL_DOMAIN]` and `https://llm.knox.lollie.org` -> reverse
  proxy to `192.168.2.133:18151`, then `192.168.2.150:18151`, then
  `192.168.2.151:18151`

The Caddy reverse proxy uses first-healthy load balancing with active health
checks. That keeps 2.133 as the preferred front door while allowing 150/151 to
carry requests when 2.133 is unavailable. The LLM route uses a longer upstream
selection window (`lb_try_duration 15s`) and short active health interval
(`health_interval 3s`) so a recovering spark can rejoin quickly after a reboot
or power-cycle without clients needing direct worker addresses.

The split DNS records point both names at Norman:

```text
llm.[INTERNAL_DOMAIN]        192.168.2.241
llm.knox.lollie.org  192.168.2.241
```

## Optional Mac Mini Caddy

If the Mac mini later gets a managed root/Homebrew service path, it can run its
own Caddy. The repo-owned renderer for that optional shape is:

- `scripts/render_mac_mini_llm_caddy.py`
- `scripts/render_mac_mini_llm_launchd.py --service caddy`

It produces:

- `http://llm.[INTERNAL_DOMAIN]` -> `https://llm.[INTERNAL_DOMAIN]`
- `http://llm.knox.lollie.org` -> `https://llm.knox.lollie.org`
- `https://llm.[INTERNAL_DOMAIN]` and `https://llm.knox.lollie.org` -> reverse
  proxy to `127.0.0.1:18151`

Typical render:

```bash
python3 scripts/render_mac_mini_llm_caddy.py
```

If Caddy should be managed directly by `launchd`, render the plist:

```bash
python3 scripts/render_mac_mini_llm_launchd.py --service caddy
```

## Norman Config

For Norman's app-side offline provider, prefer the logical local front door:

```yaml
llm_offline_provider: "openai_compatible"
llm_offline_api_key: "ollama"
llm_offline_base_url: "https://llm.[INTERNAL_DOMAIN]/v1"
llm_offline_model: "gemma4:26b-a4b-it-q4_K_M"
```

That keeps Norman, TUIs, and humans on the same endpoint while Caddy/Norllama
own worker failover behind it.

## TUI Local Lane

The shared agent console template autosenses Norman Norllama by default. A TUI
with no explicit local LLM env now starts with:

- default local model: `gemma4:26b-a4b-it-q4_K_M`
- local Qwen floor: `3.5`
- autosense enabled: `NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED=1`
- candidate endpoints, in order: `https://llm.[INTERNAL_DOMAIN]`, then
  `https://llm.knox.lollie.org`

Operators can override this with `NORMAN_LOCAL_LLM_ENDPOINTS`,
`NORMAN_LOCAL_LLM_FRONTDOORS`, or `NORMAN_LOCAL_LLM_AUTOSENSE_ENDPOINTS`. Set
`NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED=0` only when a console must fail closed
without an explicit local endpoint.

Current Hal consoles also carry systemd drop-ins for the local lane:

```text
NORMAN_LOCAL_LLM_MODEL=gemma4:26b-a4b-it-q4_K_M
NORMAN_LOCAL_LLM_MODELS=gemma4:26b-a4b-it-q4_K_M,qwen3-coder:30b-a3b-q4_K_M,qwen3-coder-next:q4_K_M,gemma4:31b,hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M,qwen3.5:27b-q4_K_M,llama3.2:3b,llama3.2:1b
NORMAN_LOCAL_LLM_ENDPOINTS=
NORMAN_LOCAL_LLM_FRONTDOORS=https://llm.[INTERNAL_DOMAIN]
NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED=1
NORMAN_LOCAL_LLM_EXECUTION_ENABLED=1
NORMAN_CODEX_LOCAL_FIRST_ENABLED=1
NORMAN_LOCAL_LLM_QWEN_MIN_VERSION=3.5
```

The selected UI runtime may still display Codex by default. That is expected:
local-first routing only redirects safe, self-contained prompts such as summary,
classification, rewrite, extract, or translation work after Norllama health
passes. The local-first gate tries the configured Norllama model list in order,
so a temporarily cold or unavailable preferred model can fall through to the next
healthy benchmark-era local model before cloud fallback. Prompts that mention
code edits, tests, deploys, SSH, services, the repo, or other workspace/tool work
stay on the tool-capable runtime.

The same template also runs a bounded Norllama planner preflight for cloud/tool
turns when a local endpoint is healthy. That planner receives only a compact
prompt preview, TUI memory references, attachment-saving metadata, and route
metadata. It can advise on offline scout/filter/rerank/summarize steps and why a
cloud/tool escalation is needed, but it cannot claim file, shell, deployment,
secret, or network access. The resulting `planner.local-preflight` audit event is
mirrored into the console-runtime feed so TUIs can show the planner behavior.

Useful knobs:

```text
NORMAN_LOCAL_PLANNER_PREFLIGHT_ENABLED=1
NORMAN_LOCAL_PLANNER_PREFLIGHT_TIMEOUT_SECONDS=15
NORMAN_LOCAL_PLANNER_PREFLIGHT_MAX_OUTPUT_TOKENS=480
NORMAN_LOCAL_PLANNER_PREFLIGHT_PROMPT_CHARS=2400
NORMAN_LOCAL_PLANNER_PREFLIGHT_MAX_CANDIDATES=1
NORMAN_LOCAL_PLANNER_PREFLIGHT_MODELS=hf.co/mradermacher/openfugu-conductor-3b-GGUF:q4_K_M
```

The planner model list is intentionally separate from `NORMAN_LOCAL_LLM_MODELS`:
the former should stay small and fast for cheap preflight, while the latter can
prefer larger Qwen/Gemma/Devstral models for local execution when latency allows.

## Process Control

Treat model residency as the thing that spins up and down, not the whole
machine:

- keep the Ollama service running
- let models unload aggressively with `keep_alive`
- use `ollama stop <model>` when you want memory back immediately

The repo-owned native service renderer is:

- `scripts/render_mac_mini_llm_launchd.py --service ollama`
- `scripts/render_mac_mini_llm_launchd.py --service norllama`

Typical Ollama render. This should stay loopback-only:

```bash
python3 scripts/render_mac_mini_llm_launchd.py --service ollama
```

For the current Mac mini app install path, render with the bundled Ollama binary:

```bash
python3 scripts/render_mac_mini_llm_launchd.py \
  --service ollama \
  --ollama-bin /Users/k/Applications/Ollama.app/Contents/Resources/ollama \
  --host 127.0.0.1:11434 \
  --user-name k \
  --group-name staff \
  --home-dir /Users/k \
  --models-dir /Users/k/.ollama/models \
  --log-dir /Users/k/Library/Logs
```

Typical Norllama render:

```bash
python3 scripts/render_mac_mini_llm_launchd.py \
  --service norllama \
  --norllama-gateway /Users/k/norllama/norllama_gateway.py \
  --norllama-working-dir /Users/k/norllama \
  --norllama-bind 0.0.0.0 \
  --norllama-port 18151 \
  --norllama-ollama-bases http://127.0.0.1:11434,http://192.168.2.150:18151,http://192.168.2.151:18151 \
  --norllama-peer-bases http://192.168.2.150:18151,http://192.168.2.151:18151 \
  --norllama-self-base http://192.168.2.133:18151 \
  --user-name k \
  --group-name staff \
  --log-dir /Users/k/Library/Logs
```

The gateway source deployed at `/Users/k/norllama/norllama_gateway.py` is
repo-owned at `scripts/norllama/norllama_gateway.py`. Use the deploy helper to
copy that exact source and restart the front-door service:

```bash
scripts/norllama/deploy_gateway.sh --mac-only
```

When the Spark peer services should receive the same gateway code, use:

```bash
scripts/norllama/deploy_gateway.sh --all
```

The Spark restart path uses `sudo -n systemctl restart norllama-gateway.service`;
if passwordless sudo is not configured, copy/compile still works but the worker
restart must be brokered by the operator.

That keeps the fast path native on macOS while still giving you a small,
controllable service boundary. If stricter control is needed later, use this
`launchd` wrapper before forcing the node into a Linux VM.

For reboot survival before login, install both rendered plists as
`/Library/LaunchDaemons` entries with `UserName=k` and `GroupName=staff`.
Without that admin step, a `~/Library/LaunchAgents` Norllama plist survives user
login but is not a true boot service.

On the Ubuntu large-worker nodes, keep both units enabled:

```bash
sudo systemctl enable ollama.service norllama-gateway.service
sudo systemctl restart ollama.service norllama-gateway.service
```

Worker `/etc/default/norllama-gateway` should expose Norllama and keep Ollama
private. Each worker should also list its peer gateways explicitly:

```text
NORLLAMA_BIND=0.0.0.0
NORLLAMA_PORT=18151
NORLLAMA_OLLAMA_BASES=http://127.0.0.1:11434
NORLLAMA_PEER_BASES=http://192.168.2.133:18151,http://192.168.2.151:18151
NORLLAMA_SELF_BASE=http://192.168.2.150:18151
NORLLAMA_MAX_PEER_HOPS=1
NORLLAMA_PEER_TIMEOUT_S=1.5
```

Use the matching peer list/self base on 2.151.

The worker Ollama systemd drop-in should bind only loopback:

```text
Environment="OLLAMA_HOST=127.0.0.1:11434"
```

## Exposure Policy

Only Norllama should be reachable from the LAN or Norman front door. Direct
Ollama listeners should be loopback-only. The intended live shape is:

```text
TUI / Norman app -> https://llm.[INTERNAL_DOMAIN] -> Norman Caddy -> 192.168.2.133:18151 -> Norllama -> 127.0.0.1:11434 -> Ollama
```

If 2.133 is unavailable, Norman Caddy should fail over to 150/151:

```text
TUI / Norman app -> https://llm.[INTERNAL_DOMAIN] -> Norman Caddy -> 192.168.2.150:18151 -> Norllama -> 127.0.0.1:11434 -> Ollama
TUI / Norman app -> https://llm.[INTERNAL_DOMAIN] -> Norman Caddy -> 192.168.2.151:18151 -> Norllama -> 127.0.0.1:11434 -> Ollama
```

Inside the mesh, Norllama gateways should also know their peers so requests
accepted by one gateway can route to another gateway that has the requested
model:

```text
2.133 Norllama -> 2.150 Norllama / 2.151 Norllama
2.150 Norllama -> 2.133 Norllama / 2.151 Norllama
2.151 Norllama -> 2.133 Norllama / 2.150 Norllama
```

Do not leave any LAN-addressed `:11434` listener bound to raw Ollama after the
daemon has been re-rendered. If compatibility clients must keep using port
`11434`, run Norllama or a local proxy on public `11434` and move Ollama to a
different private loopback port such as `127.0.0.1:11435`. That is an
inference-client compatibility move; model management commands should continue
to target the private Ollama backend until Norllama proxies the full Ollama
management API.

## Health Checks

Use `/api/version`, `/healthz`, or `/v1/overview` for Norllama gateway
identity. Even though `/api/version` is an Ollama-shaped path for client
compatibility, on a Norllama endpoint it reports the Norllama gateway version.

```bash
curl https://llm.[INTERNAL_DOMAIN]/healthz
curl https://llm.[INTERNAL_DOMAIN]/v1/overview
```

The gateway identity appears under `gateway`:

```json
{
  "name": "norllama",
  "version": "0.1.20260702",
  "build": "worker-frontdoor-unified",
  "version_endpoint": "norllama"
}
```

The catalog endpoint is:

```bash
curl https://llm.[INTERNAL_DOMAIN]/api/tags
```

For the fallback lane, use the 3B default for quick health checks:

```bash
curl https://llm.[INTERNAL_DOMAIN]/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"llama3.2:3b","prompt":"Reply exactly: NORMAN-LLM-OK","stream":false,"options":{"temperature":0,"num_predict":64}}'
```

For Qwen3 health checks, disable thinking to avoid spending a small token budget
on reasoning.

## Road Access

There are two viable road-access shapes.

Preferred shape:

- Knox split DNS: `llm.[INTERNAL_DOMAIN] -> 192.168.2.241`
- Knox split DNS: `llm.knox.lollie.org -> 192.168.2.241`
- public DNS: `llm.knox.lollie.org -> 100.103.34.17`

`100.103.34.17` is Norman's Tailscale IP. That path works without a subnet
route because the phone reaches Norman directly over Tailscale, while Knox LAN
clients keep using the lower-latency LAN front door through pfSense split DNS.
LAN clients should prefer `llm.[INTERNAL_DOMAIN]`; road clients can use
`llm.knox.lollie.org`.

Fallback shape:

Public DNS currently resolves `llm.knox.lollie.org` to `192.168.2.241`, the
Norman LAN front door. That is correct on the Knox LAN. For a phone on 5G, the
tailnet also needs a route to that LAN front door address. Norman advertises
the minimal route:

```text
192.168.2.241/32
```

If the route is not visible in peers' `AllowedIPs`, approve the advertised route
for the Norman node in the Tailscale admin console. Use a full
`192.168.2.0/24` subnet route later only when the whole Knox LAN should be
reachable by road clients.

Current verification:

```bash
curl --resolve llm.knox.lollie.org:443:100.103.34.17 https://llm.knox.lollie.org/api/tags
```

That confirms Norman's Tailscale IP can serve the road hostname once public DNS
is changed.

## Suggested Rollout

1. Install native Ollama on the Mac mini.
2. Render the `ollama` plist from `scripts/render_mac_mini_llm_launchd.py` with
   `--host 127.0.0.1:11434`.
3. Render the `norllama` plist from `scripts/render_mac_mini_llm_launchd.py`
   with `--norllama-ollama-bases http://127.0.0.1:11434`.
4. Install both plists as LaunchDaemons for true reboot survival, or as
   LaunchAgents as a temporary login-scoped bridge.
5. Render and deploy Norman's Caddy include from `scripts/render_norman_bot_proxy_caddy.py`.
6. Publish `llm.knox.lollie.org` and `llm.[INTERNAL_DOMAIN]` in Knox split DNS to Norman.
7. Pull the tiny fallback set on the Mac mini: `llama3.2:3b`,
   `llama3.2:1b`, `gemma3:1b`, `gemma3:4b`, `qwen3:1.7b`, `qwen3:4b`,
   and `qwen3:8b`.
8. Point Norman's offline provider at `https://llm.[INTERNAL_DOMAIN]/v1`. TUI
   local-first routes autosense Norman Norllama by default and should not need
   direct worker addresses.
9. Add 150/151 as remote upstreams on the 2.133 Norllama gateway, and add the
   other two gateways as peers on each worker, so clients can keep using one
   logical Norllama endpoint for tiny and large models.
10. When SSH/admin access to 150/151 is available, install native Norllama on
    each worker, bind each worker's Ollama to loopback, and remove direct LAN
    `:11434` exposure.
