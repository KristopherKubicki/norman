# Perplexity Computer on the DGX Spark fleet

Perplexity Computer is a local orchestration client, not Norman's upstream
model API. The supported integration is for Perplexity Computer and
`codex-work` to share the same Norman/Norllama inference plane:

```text
Perplexity Computer (Local mode) ─┐
                                  ├─> Norman/Norllama ─> DGX Spark local model
codex-work ─> Norman gateway ─────┘                         │
                                                           └─> Bedrock Mantle
                                                               account 770
                                                               on retryable
                                                               pre-output failure
```

This keeps Perplexity's local subagent harness available without depending on
an undocumented private RPC protocol. It also leaves fallback, credentials,
route receipts, and policy enforcement under Norman's control.

## Spark 150

The packaged Perplexity app is `/opt/Perplexity/perplexity`. In Settings,
select Local Inference, enable Local mode and Privacy Gate, disable external
web search, connectors, and adviser escalation, and configure this custom
OpenAI-compatible endpoint:

```text
http://127.0.0.1:18151/v1
```

An API key is not required for the loopback endpoint. The current interim
model is `local:latest`, a 27.8B Qwen-family local model. Replace it with the
official PPLX 27B model after the native engine is authorized.

The official vLLM engine requires a one-time privileged Docker setup. Run this
on the Spark, then sign out and back in (or reboot) so group membership is
refreshed:

```bash
sudo usermod -aG docker "$USER"
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Afterward, return to Perplexity's Local Inference settings and install PPLX
27B. Keep the custom Norman endpoint configured as the recovery endpoint until
the native-model canary has passed.

## Spark 151

The arm64 package is staged at:

```text
/home/kristopher/Downloads/perplexity_26.8.4+build50522_arm64.deb
```

Install it and configure Docker with:

```bash
sudo apt install /home/kristopher/Downloads/perplexity_26.8.4+build50522_arm64.deb
sudo usermod -aG docker "$USER"
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

After login/reboot, sign into the corporate Perplexity account and mirror the
Spark 150 Local Inference settings. Do not copy Electron session state or
browser credentials between the Sparks.

## Acceptance

For each Spark:

1. Confirm `http://127.0.0.1:18151/v1/models` returns the local catalog.
2. Run a Perplexity Computer Local session that asks for a short, unique token.
3. Confirm the Norllama activity receipt names the local Spark endpoint and no
   external-search or adviser-escalation event occurred.
4. Stop local capacity before output and run a `codex-work` prompt through
   Norman. Confirm the route receipt reports `openai.gpt-5.6-terra`, the
   Bedrock Mantle Responses transport, and AWS account `770311548538`.

Never expose the Mantle access key or generated bearer token in a Perplexity
setting, Codex config, environment file, route receipt, or transcript.

## Parked Norman integration plan

Status: design note only; implementation awaits operator approval.

- Keep `pplx-local` and `perplexity_web` as separate providers and usage
  buckets. Local inference is not Perplexity Search API usage.
- Canary Spark 151 as the Perplexity-local worker behind a stable,
  loopback-only adapter that discovers the app-owned vLLM port without
  managing or exposing the Perplexity container.
- Use the local lane for query planning, extraction, summarization, context
  compression, drafting, and read-only verification before Bedrock Mantle.
- For fresh research, have local inference formulate a narrow search request,
  use an explicitly metered Perplexity Search/Agent API lane, then synthesize
  and validate the cited evidence locally.
- Keep Spark 150 as the normal Qwen 3.8 resident during the canary so the two
  large local engines do not compete on one node. Preserve Bedrock account 770
  as receipted fallback and reserve Sol for genuinely frontier work.
- Measure local completions, Perplexity search usage, Bedrock tokens avoided,
  fallback rate, citation quality, latency, and GPU contention before
  promotion.
