from __future__ import annotations

import ipaddress
import time
import warnings
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from urllib3.exceptions import InsecureRequestWarning

from app.core.config import settings


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {"1", "true", "yes", "on", "adult", "nsfw"}


def messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = _clean(message.get("role")) or "user"
        content = _clean(message.get("content"))
        if content:
            parts.append(f"{role.upper()}:\n{content}")
    return "\n\n".join(parts)


def _frontdoor_url(base_url: str, path: str) -> str:
    normalized = base_url.rstrip("/") + "/"
    clean_path = path.strip("/")
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return urljoin(normalized, clean_path)
    base_path = parsed.path.rstrip("/")
    if base_path.endswith("/v1") and (
        clean_path.startswith("api/") or clean_path.startswith("v1/")
    ):
        root_path = base_path[: -len("/v1")]
        new_path = (
            f"{root_path.rstrip('/')}/{clean_path}" if root_path else f"/{clean_path}"
        )
        return urlunsplit((parsed.scheme, parsed.netloc, new_path, "", ""))
    return urljoin(normalized, clean_path)


def _root_frontdoor_url(base_url: str, path: str) -> str:
    normalized = base_url.rstrip("/") + "/"
    clean_path = path.strip("/")
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return urljoin(normalized, clean_path)
    base_path = parsed.path.rstrip("/")
    if base_path.endswith("/v1"):
        root_path = base_path[: -len("/v1")]
        new_path = (
            f"{root_path.rstrip('/')}/{clean_path}" if root_path else f"/{clean_path}"
        )
        return urlunsplit((parsed.scheme, parsed.netloc, new_path, "", ""))
    return urljoin(normalized, clean_path)


def _dedupe_urls(urls: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for url in urls:
        clean = _clean(url)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _generate_url(base_url: str) -> str:
    return _frontdoor_url(base_url, "api/generate")


def _capability_urls(base_url: str) -> list[str]:
    try:
        parsed = urlsplit(base_url.rstrip("/") + "/")
        versioned_base = parsed.path.rstrip("/").endswith("/v1")
    except ValueError:
        versioned_base = False
    paths = (
        [
            _frontdoor_url(base_url, "v1/capabilities"),
            _frontdoor_url(base_url, "capabilities"),
            _frontdoor_url(base_url, "api/capabilities"),
            _frontdoor_url(base_url, "api/tags"),
            _frontdoor_url(base_url, "v1/models"),
        ]
        if versioned_base
        else [
            _frontdoor_url(base_url, "api/capabilities"),
            _frontdoor_url(base_url, "v1/capabilities"),
            _frontdoor_url(base_url, "capabilities"),
            _frontdoor_url(base_url, "api/tags"),
            _frontdoor_url(base_url, "v1/models"),
        ]
    )
    return _dedupe_urls(paths)


def _overview_urls(base_url: str) -> list[str]:
    return _dedupe_urls(
        [
            _frontdoor_url(base_url, "v1/overview"),
            _frontdoor_url(base_url, "overview"),
            _frontdoor_url(base_url, "api/overview"),
            _root_frontdoor_url(base_url, "healthz"),
        ]
    )


def _api_ps_url(base_url: str) -> str:
    return _frontdoor_url(base_url, "api/ps")


def _prefetch_url(base_url: str) -> str:
    return _frontdoor_url(base_url, "v1/prefetch")


def _rerank_url(base_url: str) -> str:
    return _frontdoor_url(base_url, "v1/rerank")


def _safety_classify_url(base_url: str) -> str:
    return _frontdoor_url(base_url, "v1/safety/classify")


def _image_generation_url(base_url: str) -> str:
    return _frontdoor_url(base_url, "v1/images/generations")


def _activity_url(base_url: str, limit: int) -> str:
    clean_limit = max(1, min(int(limit or 200), 1000))
    return f"{_frontdoor_url(base_url, 'v1/activity')}?limit={clean_limit}"


def _public_endpoint(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.split("?", 1)[0]
    if not parsed.netloc:
        return raw.split("?", 1)[0]
    netloc = parsed.hostname or parsed.netloc.rsplit("@", 1)[-1]
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _verify_tls_for_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return True
    if parsed.scheme.lower() != "https":
        return True
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        return True
    if host in {"localhost", "llm.home.arpa"} or host.endswith(".home.arpa"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not bool(address.is_private or address.is_loopback or address.is_link_local)


def _requests_get(url: str, *, headers: dict[str, str], timeout: float):
    verify = _verify_tls_for_url(url)
    if verify:
        return requests.get(url, headers=headers, timeout=timeout, verify=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureRequestWarning)
        return requests.get(url, headers=headers, timeout=timeout, verify=False)


def _requests_post(
    url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float
):
    verify = _verify_tls_for_url(url)
    if verify:
        return requests.post(
            url, headers=headers, json=json, timeout=timeout, verify=True
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureRequestWarning)
        return requests.post(
            url, headers=headers, json=json, timeout=timeout, verify=False
        )


def _usage_from_ollama(payload: dict[str, Any]) -> dict[str, int]:
    prompt_tokens = int(payload.get("prompt_eval_count") or 0)
    completion_tokens = int(payload.get("eval_count") or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def _routing_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", {}) or {}
    result: dict[str, str] = {}
    for key, value in dict(headers).items():
        clean_key = _clean(key).lower()
        if clean_key.startswith("x-norllama-"):
            result[clean_key] = _clean(value)
    return result


def _disable_native_thinking(model: str) -> bool:
    clean = _clean(model).lower()
    return clean.startswith("qwen3.6:") or clean.startswith("qwen3.5:")


def invoke_text_chat(
    *,
    messages: list[dict[str, Any]],
    model: str,
    base_url: str,
    max_tokens: int,
    api_key: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Invoke a native Ollama/Norllama text lane and return OpenAI-like data."""

    if not _clean(base_url):
        raise RuntimeError("Norllama base URL is not configured")
    if not _clean(model):
        raise RuntimeError("Norllama model is not configured")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request_payload: dict[str, Any] = {
        "model": model,
        "prompt": messages_to_prompt(messages),
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": max(1, int(max_tokens or 1)),
        },
    }
    if _disable_native_thinking(model):
        request_payload["think"] = False
    response = _requests_post(
        _generate_url(base_url),
        headers=headers,
        json=request_payload,
        timeout=timeout_seconds
        or max(1, min(float(settings.llm_provider_timeout_seconds), 120.0)),
    )
    response.raise_for_status()
    payload = response.json()
    text = _clean(payload.get("response"))
    if not text:
        raise RuntimeError("Norllama returned an empty response")
    return {
        "model": _clean(payload.get("model")) or model,
        "choices": [{"message": {"content": text}}],
        "usage": _usage_from_ollama(payload),
        "headers": _routing_headers(response),
        "raw": payload,
    }


def rerank_documents(
    *,
    query: str,
    documents: list[Any],
    base_url: str,
    model: str = "",
    api_key: str = "",
    top_n: int | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Invoke the Norllama rerank specialist lane through the front door."""

    frontdoor = _clean(base_url) or _clean(
        getattr(settings, "llm_offline_base_url", "")
    )
    clean_query = _clean(query)
    if not frontdoor:
        raise RuntimeError("Norllama base URL is not configured")
    if not clean_query:
        raise RuntimeError("Norllama rerank query is missing")
    if not documents:
        raise RuntimeError("Norllama rerank documents are missing")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    key = api_key if api_key else _clean(getattr(settings, "llm_offline_api_key", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request_payload: dict[str, Any] = {
        "query": clean_query,
        "documents": documents,
    }
    if _clean(model):
        request_payload["model"] = _clean(model)
    if top_n is not None:
        request_payload["top_n"] = max(1, int(top_n))
    response = _requests_post(
        _rerank_url(frontdoor),
        headers=headers,
        json=request_payload,
        timeout=timeout_seconds
        or max(1, min(float(settings.llm_provider_timeout_seconds), 120.0)),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        payload = {}
    return {
        "model": _clean(payload.get("model")) or _clean(model),
        "results": payload.get("results")
        if isinstance(payload.get("results"), list)
        else [],
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "headers": _routing_headers(response),
        "raw": payload,
    }


def classify_safety(
    *,
    text: str,
    base_url: str,
    model: str = "",
    api_key: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Invoke the Norllama safety/prompt-injection specialist lane."""

    frontdoor = _clean(base_url) or _clean(
        getattr(settings, "llm_offline_base_url", "")
    )
    clean_text = _clean(text)
    if not frontdoor:
        raise RuntimeError("Norllama base URL is not configured")
    if not clean_text:
        raise RuntimeError("Norllama safety text is missing")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    key = api_key if api_key else _clean(getattr(settings, "llm_offline_api_key", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request_payload: dict[str, Any] = {"text": clean_text}
    if _clean(model):
        request_payload["model"] = _clean(model)
    response = _requests_post(
        _safety_classify_url(frontdoor),
        headers=headers,
        json=request_payload,
        timeout=timeout_seconds
        or max(1, min(float(settings.llm_provider_timeout_seconds), 120.0)),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        payload = {}
    return {
        "model": _clean(payload.get("model")) or _clean(model),
        "risk_level": _clean(payload.get("risk_level")),
        "category": _clean(payload.get("category")),
        "confidence": payload.get("confidence"),
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "headers": _routing_headers(response),
        "raw": payload,
    }


def generate_image(
    *,
    prompt: str,
    base_url: str,
    model: str = "",
    api_key: str = "",
    negative_prompt: str = "",
    size: str = "1024x1024",
    n: int = 1,
    steps: int | None = None,
    cfg_scale: float | None = None,
    seed: int | None = None,
    sampler: str = "",
    allow_nsfw: bool = False,
    content_rating: str = "",
    safety_profile: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Invoke the Norllama Stable Diffusion-compatible image lane."""

    frontdoor = _clean(base_url) or _clean(
        getattr(settings, "llm_offline_base_url", "")
    )
    clean_prompt = _clean(prompt)
    if not frontdoor:
        raise RuntimeError("Norllama base URL is not configured")
    if not clean_prompt:
        raise RuntimeError("Norllama image prompt is missing")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    key = api_key if api_key else _clean(getattr(settings, "llm_offline_api_key", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request_payload: dict[str, Any] = {
        "prompt": clean_prompt,
        "n": max(1, min(int(n or 1), 4)),
        "size": _clean(size) or "1024x1024",
    }
    rating = _clean(content_rating)
    nsfw_enabled = _truthy(allow_nsfw) or rating.lower() in {
        "adult",
        "explicit",
        "nsfw",
    }
    rating = rating or ("adult" if nsfw_enabled else "standard")
    request_payload["allow_nsfw"] = nsfw_enabled
    request_payload["content_rating"] = rating
    if _clean(safety_profile):
        request_payload["safety_profile"] = _clean(safety_profile)
    if _clean(model):
        request_payload["model"] = _clean(model)
    if _clean(negative_prompt):
        request_payload["negative_prompt"] = _clean(negative_prompt)
    if steps is not None:
        request_payload["steps"] = max(1, min(int(steps), 150))
    if cfg_scale is not None:
        request_payload["cfg_scale"] = float(cfg_scale)
    if seed is not None:
        request_payload["seed"] = int(seed)
    if _clean(sampler):
        request_payload["sampler"] = _clean(sampler)
    response = _requests_post(
        _image_generation_url(frontdoor),
        headers=headers,
        json=request_payload,
        timeout=timeout_seconds
        or max(1, min(float(settings.llm_provider_timeout_seconds), 300.0)),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), list) else []
    image_count = len([item for item in data if isinstance(item, dict)])
    return {
        "model": _clean(payload.get("model")) or _clean(model),
        "data": data,
        "image_count": image_count,
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
        "headers": _routing_headers(response),
        "raw": payload,
    }


def prefetch_model(
    *,
    model: str,
    base_url: str = "",
    api_key: str = "",
    priority: str = "background",
    source: str = "norman",
    target_worker: str = "",
    target_endpoint: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Ask Norllama to warm a model through the frontdoor prefetch API."""

    clean_model = _clean(model)
    frontdoor = _clean(base_url) or _clean(
        getattr(settings, "llm_offline_base_url", "")
    )
    if not frontdoor:
        raise RuntimeError("Norllama base URL is not configured")
    if not clean_model:
        raise RuntimeError("Norllama prefetch model is not configured")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Norllama-Priority": _clean(priority) or "background",
    }
    clean_target_worker = _clean(target_worker)
    clean_target_endpoint = _clean(target_endpoint)
    if clean_target_worker:
        headers["X-Norllama-Target-Worker"] = clean_target_worker
    if clean_target_endpoint:
        headers["X-Norllama-Target-Endpoint"] = clean_target_endpoint
    key = api_key if api_key else _clean(getattr(settings, "llm_offline_api_key", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    timeout = timeout_seconds or max(
        1, min(float(settings.llm_provider_timeout_seconds), 30.0)
    )
    response = _requests_post(
        _prefetch_url(frontdoor),
        headers=headers,
        json={
            "model": clean_model,
            "priority": _clean(priority) or "background",
            "source": _clean(source) or "norman",
            "target_worker": clean_target_worker,
            "target_endpoint": clean_target_endpoint,
        },
        timeout=timeout,
    )
    if response.status_code == 204:
        return {
            "ok": True,
            "status": "accepted",
            "model": clean_model,
            "response_status": 204,
        }
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("ok", True)
    payload.setdefault("status", "accepted")
    payload.setdefault("model", clean_model)
    return payload


def _model_names(value: Any) -> list[str]:
    models = value if isinstance(value, list) else []
    names: list[str] = []
    for item in models:
        if isinstance(item, str):
            name = _clean(item)
        elif isinstance(item, dict):
            name = _clean(item.get("name") or item.get("model") or item.get("id"))
        else:
            name = ""
        if name and name not in names:
            names.append(name)
    return names


def _models_from_openai_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("id") or item.get("name") or item.get("model"))
        if name and name not in names:
            names.append(name)
    return names


def _list_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _clean(item)
        if text and text not in result:
            result.append(text)
    return result


def _append_unique(values: list[str], *items: str) -> None:
    for item in items:
        clean = _clean(item)
        if clean and clean not in values:
            values.append(clean)


CONTRACT_TASK_KIND_MAP = {
    "audio_diarize": ("stt", "asr"),
    "code_risk": ("code", "safety"),
    "doc_parse": ("doc_parse", "ocr"),
    "embed": ("embed",),
    "entity_event_extract": ("filter",),
    "gui_ground": ("gui_ground",),
    "hybrid_retrieve": ("embed", "rerank"),
    "ops_anomaly": ("filter", "forecast"),
    "prompt_injection": ("prompt_injection",),
    "rerank": ("rerank",),
    "safety_privacy_classify": ("safety",),
    "image_generate": ("image_generate",),
    "stable_diffusion": ("image_generate",),
    "vision_grounding": ("gui_ground", "doc_parse"),
    "world": ("world",),
    "web_world": ("world", "gui_ground"),
}
DISPATCH_TASK_KIND_MAP = {
    "embedding_proxy": ("embed",),
    "hybrid_pipeline": ("embed", "rerank"),
    "media_proxy": ("doc_parse", "ocr", "gui_ground"),
    "image_generation_proxy": ("image_generate",),
    "rerank_proxy": ("rerank",),
    "safety_proxy": ("safety", "prompt_injection"),
    "transcribe_proxy": ("stt", "asr"),
    "world_proxy": ("world",),
}
ENDPOINT_KIND_TASK_KIND_MAP = {
    "audio": ("stt", "asr"),
    "embedding": ("embed",),
    "media": ("ocr", "doc_parse", "gui_ground"),
    "image": ("image_generate",),
    "image_generate": ("image_generate",),
    "stable_diffusion": ("image_generate",),
    "moderation": ("safety",),
    "prompt_injection": ("prompt_injection",),
    "rerank": ("rerank",),
    "safety": ("safety", "prompt_injection"),
    "transcribe": ("stt", "asr"),
    "world": ("world",),
}


def _contract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    contracts = payload.get("contracts")
    if not isinstance(contracts, list):
        contracts = payload.get("capability_contracts")
    if not isinstance(contracts, list):
        return []
    return [item for item in contracts if isinstance(item, dict)]


def _endpoint_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list):
        return []
    return [item for item in endpoints if isinstance(item, dict)]


def _contract_task_kinds(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for contract in _contract_items(payload):
        contract_id = _clean(contract.get("contract_id")).lower()
        dispatch = _clean(contract.get("dispatch")).lower()
        _append_unique(result, *CONTRACT_TASK_KIND_MAP.get(contract_id, ()))
        _append_unique(result, *DISPATCH_TASK_KIND_MAP.get(dispatch, ()))
    for endpoint in _endpoint_items(payload):
        kind = _clean(endpoint.get("kind")).lower()
        _append_unique(result, *ENDPOINT_KIND_TASK_KIND_MAP.get(kind, ()))
        path = _clean(endpoint.get("path")).lower()
        for marker, mapped in (
            ("audio", ("stt", "asr")),
            ("transcrib", ("stt", "asr")),
            ("asr", ("stt", "asr")),
            ("ocr", ("ocr", "doc_parse")),
            ("rerank", ("rerank",)),
            ("safety", ("safety", "prompt_injection")),
            ("prompt_injection", ("prompt_injection",)),
            ("moderation", ("safety",)),
            ("embedding", ("embed",)),
            ("images/generations", ("image_generate",)),
            ("txt2img", ("image_generate",)),
            ("stable_diffusion", ("image_generate",)),
            ("world", ("world",)),
        ):
            if marker in path:
                _append_unique(result, *mapped)
    return result


def _contract_model_names(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for contract in _contract_items(payload):
        _append_unique(result, _clean(contract.get("default_model")))
        for alternate in contract.get("alternates") or []:
            if isinstance(alternate, dict):
                _append_unique(result, _clean(alternate.get("model")))
    return result


def _contract_modalities(payload: dict[str, Any]) -> list[str]:
    modalities: list[str] = []
    for contract in _contract_items(payload):
        dispatch = _clean(contract.get("dispatch")).lower()
        contract_id = _clean(contract.get("contract_id")).lower()
        if dispatch in {"media_proxy", "transcribe_proxy"}:
            _append_unique(modalities, "file")
        if dispatch == "media_proxy" or contract_id in {
            "doc_parse",
            "vision_grounding",
        }:
            _append_unique(modalities, "image", "pdf")
        if dispatch == "transcribe_proxy" or contract_id == "audio_diarize":
            _append_unique(modalities, "audio")
        if dispatch == "image_generation_proxy" or contract_id in {
            "image_generate",
            "stable_diffusion",
        }:
            _append_unique(modalities, "image")
    return modalities


TOOL_ACTIVITY_PATH_CAPABILITIES = {
    "/v1/embeddings": "embed",
    "/api/embeddings": "embed",
    "/v1/rerank": "rerank",
    "/rerank": "rerank",
    "/v1/safety/classify": "safety",
    "/safety/classify": "safety",
    "/v1/moderations": "safety",
    "/v1/audio/transcriptions": "asr",
    "/v1/audio/transcribe": "asr",
    "/v1/asr": "asr",
    "/v1/transcribe": "asr",
    "/transcribe": "asr",
    "/v1/media/ocr": "ocr",
    "/v1/ocr": "ocr",
    "/v1/media/doc-parse": "doc_parse",
    "/v1/doc-parse": "doc_parse",
    "/v1/gui/ground": "gui_ground",
    "/v1/world": "world",
    "/v1/images/generations": "image_generate",
    "/sdapi/v1/txt2img": "image_generate",
    "/v1/retrieve": "hybrid_retrieve",
    "/v1/hybrid-retrieve": "hybrid_retrieve",
    "/v1/hybrid_retrieve": "hybrid_retrieve",
    "/v1/prefetch": "prefetch",
    "/api/generate": "chat",
    "/v1/chat/completions": "chat",
}
TOOL_ACTIVITY_CAPABILITIES = {
    "embed",
    "embedding",
    "rerank",
    "retrieve",
    "hybrid_retrieve",
    "hybrid-retrieve",
    "ocr",
    "asr",
    "stt",
    "transcribe",
    "tts",
    "vision",
    "doc_parse",
    "gui_ground",
    "world",
    "prefetch",
    "prompt_injection",
    "safety",
    "chat",
    "code",
    "plan",
    "image_generate",
    "stable_diffusion",
}
PROBE_ACTIVITY_PATHS = {
    "/",
    "/healthz",
    "/api/tags",
    "/api/ps",
    "/api/capabilities",
    "/capabilities",
    "/v1/capabilities",
    "/v1/models",
    "/v1/overview",
    "/api/overview",
    "/overview",
    "/v1/activity",
}


def _activity_items(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    for key in ("items", "activity", "events", "requests"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _activity_path(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.split("?", 1)[0]
    return parsed.path or raw.split("?", 1)[0]


def _activity_capability(item: dict[str, Any], path: str) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    route = item.get("route") if isinstance(item.get("route"), dict) else {}
    raw = (
        item.get("capability")
        or item.get("norllama_capability")
        or item.get("task_kind")
        or item.get("kind")
        or metadata.get("capability")
        or metadata.get("task_kind")
        or route.get("capability")
        or TOOL_ACTIVITY_PATH_CAPABILITIES.get(path)
    )
    capability = _clean(raw).lower()
    if capability == "embedding":
        return "embed"
    if capability == "hybrid-retrieve":
        return "hybrid_retrieve"
    return capability


def _activity_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _activity_float(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _normalize_activity_attempts(value: Any) -> list[dict[str, Any]]:
    attempts = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    for item in attempts[:6]:
        if isinstance(item, str):
            text = _clean(item)
            if text:
                normalized.append({"target": _public_endpoint(text)})
            continue
        if not isinstance(item, dict):
            continue
        normalized_item = {
            "worker_id": _clean(
                item.get("worker_id") or item.get("id") or item.get("worker")
            ),
            "endpoint": _public_endpoint(
                item.get("endpoint") or item.get("upstream") or item.get("base_url")
            ),
            "status": item.get("status"),
            "duration_ms": _activity_float(
                item.get("duration_ms") or item.get("latency_ms")
            ),
        }
        normalized.append(
            {key: val for key, val in normalized_item.items() if val not in {"", None}}
        )
    return normalized


def normalize_tool_activity_payload(
    payload: Any,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """Return TUI-safe Norllama tool-lane activity without routine probe noise."""

    raw_items = _activity_items(payload)
    items: list[dict[str, Any]] = []
    capability_counts: dict[str, int] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path") or item.get("url") or item.get("route")
        path = _activity_path(raw_path)
        method = _clean(item.get("method")).upper() or "GET"
        capability = _activity_capability(item, path)
        is_probe = method in {"GET", "HEAD"} and path in PROBE_ACTIVITY_PATHS
        is_tool = (
            path in TOOL_ACTIVITY_PATH_CAPABILITIES
            or capability in TOOL_ACTIVITY_CAPABILITIES
            or (method not in {"GET", "HEAD"} and not is_probe)
        )
        if not is_tool or is_probe:
            continue
        status = item.get("status")
        normalized = {
            "ts": _clean(item.get("ts") or item.get("time") or item.get("created_at")),
            "method": method,
            "path": path,
            "capability": capability or TOOL_ACTIVITY_PATH_CAPABILITIES.get(path, ""),
            "status": _activity_int(status, status)
            if isinstance(status, (int, str))
            else status,
            "duration_ms": _activity_float(
                item.get("duration_ms") or item.get("latency_ms")
            ),
            "model": _clean(
                item.get("model")
                or item.get("request_model")
                or item.get("selected_model")
            ),
            "worker_id": _clean(
                item.get("worker_id")
                or item.get("norllama_worker_id")
                or item.get("selected_worker")
            ),
            "upstream": _public_endpoint(item.get("upstream")),
            "priority": _clean(item.get("priority")),
            "score_method": _clean(item.get("score_method") or item.get("method_name")),
            "request_id": _clean(item.get("request_id")),
            "attempts": _normalize_activity_attempts(item.get("attempts")),
        }
        compact = {
            key: val
            for key, val in normalized.items()
            if val != "" and val is not None and val != []
        }
        capability_key = compact.get("capability") or "tool"
        capability_counts[capability_key] = capability_counts.get(capability_key, 0) + 1
        items.append(compact)
        if len(items) >= max(1, min(int(limit or 200), 1000)):
            break
    source_count = (
        _activity_int(payload.get("count"), len(raw_items))
        if isinstance(payload, dict)
        else len(raw_items)
    )
    return {
        "schema": "norman.norllama.tool-activity.v1",
        "provider": "norllama",
        "status": "active" if items else "quiet",
        "source_count": source_count,
        "tool_call_count": len(items),
        "dropped_probe_count": max(0, len(raw_items) - len(items)),
        "capability_counts": capability_counts,
        "latest_tool_call": items[0] if items else {},
        "items": items,
        "checked_at": time.time(),
    }


def normalize_capabilities_payload(payload: dict[str, Any]) -> dict[str, Any]:
    capabilities = payload.get("capabilities")
    caps = capabilities if isinstance(capabilities, dict) else {}
    models = _model_names(payload.get("models"))
    if not models:
        models = _model_names(payload.get("available_models"))
    if not models:
        models = _models_from_openai_list(payload.get("data"))
    if not models:
        models = _contract_model_names(payload)
    tool_lanes = _list_values(
        payload.get("tool_lanes") or payload.get("tools") or caps.get("tool_lanes")
    )
    for kind in _contract_task_kinds(payload):
        if kind in {
            "asr",
            "doc_parse",
            "embed",
            "gui_ground",
            "ocr",
            "prompt_injection",
            "rerank",
            "safety",
            "stt",
            "world",
            "image_generate",
        }:
            _append_unique(tool_lanes, kind)
    task_kinds = _list_values(
        payload.get("task_kinds") or payload.get("tasks") or caps.get("task_kinds")
    )
    _append_unique(task_kinds, *_contract_task_kinds(payload))
    modalities = _list_values(payload.get("modalities") or caps.get("modalities"))
    _append_unique(modalities, *_contract_modalities(payload))
    supports_tools = bool(
        caps.get("tools")
        or caps.get("supports_tools")
        or tool_lanes
        or {
            "asr",
            "doc_parse",
            "embed",
            "gui_ground",
            "ocr",
            "prompt_injection",
            "stt",
            "rerank",
            "safety",
            "world",
            "image_generate",
        }.intersection(set(task_kinds))
    )
    supports_streaming = bool(
        caps.get("streaming")
        or caps.get("supports_streaming")
        or payload.get("streaming")
        or payload.get("supports_streaming")
    )
    supports_files = bool(
        caps.get("files")
        or caps.get("supports_files")
        or payload.get("supports_files")
        or {"file", "files", "image", "audio", "video"}.intersection(set(modalities))
    )
    return {
        "provider": _clean(payload.get("provider")) or "norllama",
        "models": models,
        "tool_lanes": tool_lanes,
        "task_kinds": task_kinds,
        "modalities": modalities,
        "supports": {
            "tools": supports_tools,
            "streaming": supports_streaming,
            "files": supports_files,
        },
        "capabilities": caps,
        "contracts": _contract_items(payload),
        "endpoints": _endpoint_items(payload),
        "raw": payload,
    }


def normalize_mesh_worker(
    item: Any,
    *,
    index: int,
) -> dict[str, Any]:
    if isinstance(item, str):
        raw = {"base_url": item}
    elif isinstance(item, dict):
        raw = dict(item)
    else:
        raw = {}
    base_url = _clean(
        raw.get("base_url") or raw.get("endpoint") or raw.get("url") or raw.get("host")
    )
    worker_id = _clean(raw.get("id") or raw.get("worker_id")) or f"worker-{index}"
    return {
        "id": worker_id,
        "name": _clean(raw.get("name")) or worker_id,
        "role": _clean(raw.get("role")) or "worker",
        "base_url": base_url,
        "public_base_url": _public_endpoint(base_url),
        "memory_gb": raw.get("memory_gb"),
        "priority": raw.get("priority", index),
        "metadata": raw.get("metadata")
        if isinstance(raw.get("metadata"), dict)
        else {},
    }


def _fetch_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    response = _requests_get(url, headers=headers, timeout=timeout)
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _active_model_names(payload: dict[str, Any]) -> list[str]:
    names = _model_names(payload.get("models"))
    if names:
        return names
    return _models_from_openai_list(payload.get("data"))


def _overview_model_names(payload: dict[str, Any]) -> list[str]:
    names = _model_names(payload.get("models"))
    if names:
        return names
    names = _models_from_openai_list(payload.get("data"))
    if names:
        return names
    highlights = payload.get("model_highlights")
    if isinstance(highlights, list):
        result: list[str] = []
        for item in highlights:
            if not isinstance(item, dict):
                continue
            name = _clean(item.get("id") or item.get("name") or item.get("model"))
            if name and name not in result:
                result.append(name)
        return result
    return []


def fetch_overview(
    *,
    base_url: str,
    api_key: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Read the richest Norllama overview/status payload available."""

    if not _clean(base_url):
        raise RuntimeError("Norllama base URL is not configured")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    timeout = timeout_seconds or max(
        1, min(float(settings.llm_provider_timeout_seconds), 30.0)
    )
    last_error: Exception | None = None
    for url in _overview_urls(base_url):
        try:
            payload = _fetch_json(url, headers=headers, timeout=timeout)
            if payload:
                return payload
        except requests.RequestException as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise RuntimeError(
            f"Norllama overview unavailable: {last_error}"
        ) from last_error
    raise RuntimeError("Norllama overview endpoint was not found")


def probe_mesh_worker(
    worker: dict[str, Any],
    *,
    api_key: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Probe one Norllama worker without exposing credentials."""

    clean_worker = normalize_mesh_worker(worker, index=int(worker.get("priority") or 0))
    started = time.perf_counter()
    base_url = clean_worker["base_url"]
    timeout = timeout_seconds or max(
        1, min(float(settings.llm_provider_timeout_seconds), 10.0)
    )
    result = {
        **clean_worker,
        "base_url": clean_worker["public_base_url"],
        "reachable": False,
        "status": "unknown",
        "latency_ms": 0,
        "models": [],
        "model_count": 0,
        "active_models": [],
        "active_model_count": 0,
        "capabilities": {},
        "gateway": {},
        "error": "",
    }
    if not base_url:
        result["status"] = "unconfigured"
        result["error"] = "missing base_url"
        return result
    try:
        overview = fetch_overview(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout,
        )
        capabilities = fetch_capabilities(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout,
        )
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        active_payload = {}
        try:
            active_payload = _fetch_json(
                _api_ps_url(base_url),
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException:
            active_payload = {}
        models = capabilities.get("models") or _overview_model_names(overview)
        active_models = _active_model_names(active_payload)
        result.update(
            {
                "reachable": True,
                "status": "ok",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "models": list(models)[:40],
                "model_count": len(models),
                "active_models": active_models[:20],
                "active_model_count": len(active_models),
                "capabilities": {
                    "supports": capabilities.get("supports", {}),
                    "tool_lanes": capabilities.get("tool_lanes", []),
                    "task_kinds": capabilities.get("task_kinds", []),
                    "modalities": capabilities.get("modalities", []),
                    "endpoints": capabilities.get("endpoints", []),
                    "contracts": capabilities.get("contracts", []),
                },
                "endpoints": capabilities.get("endpoints", []),
                "contracts": capabilities.get("contracts", []),
                "gateway": overview.get("gateway")
                if isinstance(overview.get("gateway"), dict)
                else {},
                "overview": {
                    "routing": overview.get("routing")
                    if isinstance(overview.get("routing"), dict)
                    else {},
                    "fleet": overview.get("fleet")
                    if isinstance(overview.get("fleet"), list)
                    else [],
                },
            }
        )
    except Exception as exc:
        result.update(
            {
                "status": "error",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": _clean(exc)[:240],
            }
        )
    return result


def build_mesh_overview(
    *,
    base_url: str = "",
    api_key: str = "",
    workers: list[Any] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Build a sanitized Norman-facing Norllama mesh snapshot."""

    frontdoor_url = _clean(base_url) or _clean(
        getattr(settings, "llm_offline_base_url", "")
    )
    key = api_key if api_key else _clean(getattr(settings, "llm_offline_api_key", ""))
    worker_items = (
        workers if workers is not None else getattr(settings, "llm_mesh_workers", [])
    )
    normalized_workers = [
        normalize_mesh_worker(item, index=index)
        for index, item in enumerate(worker_items or [], start=1)
    ]
    timeout = timeout_seconds or max(
        1, min(float(settings.llm_provider_timeout_seconds), 10.0)
    )
    frontdoor: dict[str, Any] = {
        "base_url": _public_endpoint(frontdoor_url),
        "reachable": False,
        "status": "unknown",
        "models": [],
        "model_count": 0,
        "catalog_summary": {},
        "gateway": {},
        "error": "",
    }
    try:
        overview = fetch_overview(
            base_url=frontdoor_url,
            api_key=key,
            timeout_seconds=timeout,
        )
        capabilities = fetch_capabilities(
            base_url=frontdoor_url,
            api_key=key,
            timeout_seconds=timeout,
        )
        models = capabilities.get("models") or _overview_model_names(overview)
        frontdoor.update(
            {
                "reachable": True,
                "status": _clean(overview.get("status")) or "ok",
                "models": list(models)[:40],
                "model_count": len(models),
                "catalog_summary": overview.get("catalog_summary")
                if isinstance(overview.get("catalog_summary"), dict)
                else {},
                "gateway": overview.get("gateway")
                if isinstance(overview.get("gateway"), dict)
                else {},
                "overview": {
                    "routing": overview.get("routing")
                    if isinstance(overview.get("routing"), dict)
                    else {},
                    "fleet": overview.get("fleet")
                    if isinstance(overview.get("fleet"), list)
                    else [],
                },
                "capabilities": {
                    "supports": capabilities.get("supports", {}),
                    "tool_lanes": capabilities.get("tool_lanes", []),
                    "task_kinds": capabilities.get("task_kinds", []),
                    "modalities": capabilities.get("modalities", []),
                    "endpoints": capabilities.get("endpoints", []),
                    "contracts": capabilities.get("contracts", []),
                },
                "endpoints": capabilities.get("endpoints", []),
                "contracts": capabilities.get("contracts", []),
            }
        )
    except Exception as exc:
        frontdoor.update({"status": "error", "error": _clean(exc)[:240]})

    probed_workers = [
        probe_mesh_worker(
            worker,
            api_key=key,
            timeout_seconds=timeout,
        )
        for worker in normalized_workers
    ]
    healthy_workers = [item for item in probed_workers if item.get("reachable")]
    degraded = bool(probed_workers) and len(healthy_workers) < len(probed_workers)
    if healthy_workers:
        status = "degraded" if degraded else "ok"
    elif frontdoor.get("reachable"):
        status = "degraded" if probed_workers else "ok"
    else:
        status = "offline"
    model_union: list[str] = []
    for item in [frontdoor, *probed_workers]:
        for model in item.get("models") or []:
            clean = _clean(model)
            if clean and clean not in model_union:
                model_union.append(clean)
    return {
        "schema": "norman.norllama.mesh.v1",
        "provider": "norllama",
        "status": status,
        "frontdoor": frontdoor,
        "workers": probed_workers,
        "worker_count": len(probed_workers),
        "healthy_worker_count": len(healthy_workers),
        "degraded": degraded or status == "offline",
        "model_count": len(model_union),
        "models": model_union[:80],
        "checked_at": time.time(),
    }


def fetch_capabilities(
    *,
    base_url: str,
    api_key: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Read Norllama capability metadata from native or Ollama-compatible endpoints."""

    if not _clean(base_url):
        raise RuntimeError("Norllama base URL is not configured")

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    last_error: Exception | None = None
    timeout = timeout_seconds or max(
        1, min(float(settings.llm_provider_timeout_seconds), 30.0)
    )
    for url in _capability_urls(base_url):
        try:
            response = _requests_get(url, headers=headers, timeout=timeout)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                continue
            return normalize_capabilities_payload(payload)
        except requests.RequestException as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise RuntimeError(
            f"Norllama capabilities unavailable: {last_error}"
        ) from last_error
    raise RuntimeError("Norllama capabilities endpoint was not found")


def fetch_tool_activity(
    *,
    base_url: str = "",
    api_key: str = "",
    limit: int = 200,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Read and normalize recent Norllama tool-lane activity for operator UIs."""

    frontdoor = _clean(base_url) or _clean(
        getattr(settings, "llm_offline_base_url", "")
    )
    if not frontdoor:
        raise RuntimeError("Norllama base URL is not configured")
    headers = {"Accept": "application/json"}
    key = api_key if api_key else _clean(getattr(settings, "llm_offline_api_key", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    timeout = timeout_seconds or max(
        1, min(float(settings.llm_provider_timeout_seconds), 10.0)
    )
    payload = _fetch_json(
        _activity_url(frontdoor, limit),
        headers=headers,
        timeout=timeout,
    )
    normalized = normalize_tool_activity_payload(payload, limit=limit)
    normalized["source"] = "v1/activity"
    normalized["base_url"] = _public_endpoint(frontdoor)
    return normalized
