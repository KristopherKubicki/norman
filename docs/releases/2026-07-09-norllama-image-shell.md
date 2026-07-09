# Norllama Image Shell

Norllama now exposes a local image generation lane for Stable Diffusion-compatible backends.

## Operator Contract

- Human UI: `/ui` includes an Image Shell panel.
- Bot/API route: `POST /v1/images/generations`.
- Upstream local backend: Stable Diffusion WebUI-compatible `POST /sdapi/v1/txt2img`.
- Default backend discovery: `NORLLAMA_IMAGE_BASES=http://127.0.0.1:7860`.
- Alias env: `NORLLAMA_STABLE_DIFFUSION_BASES` is also accepted.
- Optional auth: `NORLLAMA_IMAGE_API_KEY`, `NORLLAMA_IMAGE_API_KEY_FILE`, or `NORLLAMA_IMAGE_KEY_DIR`.
- Adult/NSFW intent is explicit: set `allow_nsfw: true` or `content_rating: "adult"`.
- Norllama forwards adult-mode intent to local backends with `X-Norllama-Allow-NSFW`, `X-Norllama-Content-Rating`, and `X-Norllama-Safety-Profile`.

The response is OpenAI-style:

```json
{
  "model": "stable-diffusion:configured-backend",
  "data": [{"b64_json": "..."}],
  "usage": {"usage_bucket": "offline_local", "image_count": 1},
  "norllama": {
    "capability": "image_generate",
    "mode": "image_generation_proxy",
    "selected_provider": "norllama",
    "content_rating": "standard",
    "allow_nsfw": false,
    "usage_bucket": "offline_local",
    "cloud_proxy": false,
    "output_shape": "complete"
  }
}
```

If no healthy image backend is available, Norllama returns `image_generation_unavailable` and records the lane as a failed local tool call rather than silently falling back to a text model or cloud image service.
