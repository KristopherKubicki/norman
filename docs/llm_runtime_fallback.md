# LLM Runtime Fallback

Norman treats hosted LLM access as the primary lane and local Ollama on the mac-mini as the offline fallback lane.

## Current Lanes

- Primary: OpenAI, using `openai_api_key` and `openai_default_model`.
- Backup: disabled until a second hosted or OpenAI-compatible provider is configured.
- Offline: Ollama at `http://192.168.0.133:11434`, model `qwen3:8b`.

The operator status API is `/api/llm/status`. It reports one of these modes:

- `primary`: hosted lane is available.
- `backup_online`: primary is unavailable, backup provider is available.
- `offline_local`: hosted lanes are unavailable, local Ollama is reachable.
- `control_only`: no LLM lane is available, so Norman should defer LLM work.

## Glimpser Snapshot

Measured on 2026-04-30:

- Norman routing has 39,244 total routing events.
- Glimpser has 1 historical Norman routing event, from 2026-02-19, and it was a failed queued test event.
- The last 24 hours of Norman routing activity was activity-monitor only, with no active Glimpser feed through Norman.
- Glimpser service health is nominal, scheduler is running, and the homepage exposes 3 active screenshot views.
- The Glimpser captions page exposes 270 named camera/page targets.
- Ollama logs show 78 total local LLM HTTP requests since the mac-mini setup window, mostly smoke tests and health checks.

This means there is not currently a production Glimpser LLM query stream to size against. If Glimpser starts sending screenshots for analysis, treat that as a new workload and add request accounting at the ingestion point.

## Model Fit

- `qwen3:8b` is the practical text fallback for Norman. It is good for short summaries, triage, and outage-mode responses.
- `gemma3:4b` is the best first local multimodal candidate for Glimpser screenshot analysis on this 16 GB M4 mac-mini.
- `qwen2.5vl:7b` is accurate on screenshots but too slow for broad Glimpser automation on this host.
- Larger 14B-class text models are possible but should be considered upgrade/testing work, not the default outage fallback.
- 30B-class local models are experimental on this host and should not be used for reliable fallback service.

Measured on 2026-05-01:

- `qwen2.5vl:7b` answered a synthetic red image correctly in about 6.8 seconds.
- `qwen2.5vl:7b` described full Glimpser screenshots accurately, but took about 148-153 seconds per image.
- `gemma3:4b` answered a synthetic red image correctly in about 6.3 seconds.
- `gemma3:4b` described real Glimpser screenshots in about 4.7-5.0 seconds per image.
- `gemma3:4b` also accepted OpenAI-compatible image input through `/v1/chat/completions`.
- `gemma3:4b` is fast for text, but weaker than `qwen3:8b` for strict JSON and fallback/defer policy decisions.
- `llama3.2-vision:11b` answered a synthetic red image correctly but took about 24.4 seconds.
- `llama3.2-vision:11b` described a real Glimpser screenshot in about 27.2 seconds with more detail than Gemma, but not enough to justify default use.
- On a generated `STOP` OCR image: `gemma3:4b` took about 6.9 seconds, `qwen2.5vl:7b` took about 5.6 seconds, and `llama3.2-vision:11b` took about 21.2 seconds. All read the word correctly.
- None of the practical installed text/vision models expose audio capability through Ollama on this host.
- `dimavz/whisper-tiny` is small and installs, but exposes only `completion` locally and failed to load for an audio probe.
- `openbmb/minicpm-o4.5:q5_K_M` advertises speech capability upstream, but this Ollama runtime exposes only `completion` and `vision`; audio probing terminated the runner and image OCR returned HTTP 500.
- Treat local audio as a separate ASR/TTS service lane, not part of Norman's Ollama text/vision fallback.
- `faster-whisper` is viable as the first ASR lane. In a temporary Norman-host venv, `tiny` and `base` transcribed a short operator phrase in about 0.6-1.0 seconds after model load; `small` took about 3.2 seconds and did not improve that sample.
- The mac-mini cannot host `faster-whisper` yet without setup work because `/usr/bin/python3` currently opens the macOS developer-tools prompt and no Homebrew/uv Python is installed.

## Defer Rules

Defer LLM work instead of attempting local fallback when:

- `/api/llm/status` returns `control_only`.
- The request needs high-quality reasoning, long context, or tool-heavy planning that local `qwen3:8b` cannot safely handle.
- The request requires screenshot/image understanding and no local multimodal model is installed.
- Glimpser screenshot analysis would require processing many of the 270 targets at once.

Use local fallback when:

- Hosted LLM access is down or being upgraded.
- The task is text-only, bounded, and can tolerate lower reasoning quality.
- The task can be summarized as "capture state, classify, or draft a short operator note."
