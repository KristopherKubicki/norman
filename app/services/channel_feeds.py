"""Local channel feed generators for demo and ops channels."""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.crud import channel_message as channel_message_crud
from app.db.session import SessionLocal
from app.schemas.channel_message import ChannelMessageCreate


FEED_TASKS: Dict[int, asyncio.Task] = {}
FEED_CONFIGS: Dict[int, Dict[str, Any]] = {}
FEED_STATE: Dict[int, Dict[str, Any]] = {}


def _safe_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _disk_usage() -> Optional[Dict[str, Any]]:
    try:
        stat = os.statvfs("/")
        total = stat.f_frsize * stat.f_blocks
        free = stat.f_frsize * stat.f_bfree
        used = total - free
        return {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "used_pct": round((used / total) * 100, 2) if total else 0,
        }
    except Exception:
        return None


def _meminfo() -> Optional[Dict[str, Any]]:
    path = "/proc/meminfo"
    if not os.path.exists(path):
        return None
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                amount = value.strip().split(" ")[0]
                data[key] = int(amount)
        mem_total = data.get("MemTotal", 0) / 1024
        mem_free = data.get("MemAvailable", 0) / 1024
        return {
            "total_mb": round(mem_total, 1),
            "available_mb": round(mem_free, 1),
            "used_mb": round(mem_total - mem_free, 1),
            "used_pct": round(((mem_total - mem_free) / mem_total) * 100, 2)
            if mem_total
            else 0,
        }
    except Exception:
        return None


async def _fetch_nist_time() -> Dict[str, Any]:
    url = "https://time.gov/actualtime.cgi"
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
    server_time = payload.get("serverTime")
    if server_time:
        try:
            ts = int(server_time) / 1000
        except ValueError:
            ts = time.time()
    else:
        ts = time.time()
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return {
        "source": "time.gov",
        "utc": dt.isoformat(),
        "epoch": int(ts),
    }


def _validate_http_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Missing url")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("Only http(s) URLs are supported")
    return url


def _preview_text(text: str, limit: int = 1200) -> str:
    if text is None:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


async def _fetch_http_poll(url: str) -> Dict[str, Any]:
    url = _validate_http_url(url)
    headers = {"User-Agent": "NormanChannelFeed/1.0"}
    async with httpx.AsyncClient(
        timeout=8, headers=headers, follow_redirects=True
    ) as client:
        started = time.time()
        resp = await client.get(url)
        elapsed_ms = int((time.time() - started) * 1000)
    content_type = resp.headers.get("content-type", "")
    text_preview = ""
    parsed_json: Optional[Any] = None
    try:
        if "application/json" in content_type:
            parsed_json = resp.json()
        else:
            text_preview = _preview_text(resp.text)
    except Exception:
        text_preview = _preview_text(getattr(resp, "text", ""))
    return {
        "source": "http_poll",
        "url": url,
        "status_code": resp.status_code,
        "elapsed_ms": elapsed_ms,
        "content_type": content_type,
        "json": parsed_json,
        "text_preview": text_preview,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_feed_xml(xml_text: str) -> Optional[Dict[str, Any]]:
    import xml.etree.ElementTree as ET

    if not xml_text:
        return None
    root = ET.fromstring(xml_text)
    tag = _strip_ns(root.tag).lower()

    # Atom: <feed><entry>...
    if tag == "feed":
        entries = list(root.findall(".//{*}entry"))
        if not entries:
            return None
        entry = entries[0]
        title = (entry.findtext(".//{*}title") or "").strip()
        link_el = entry.find(".//{*}link")
        link = ""
        if link_el is not None:
            link = (link_el.attrib.get("href") or "").strip()
        published = (entry.findtext(".//{*}updated") or "").strip() or (
            entry.findtext(".//{*}published") or ""
        ).strip()
        return {"format": "atom", "title": title, "link": link, "published": published}

    # RSS: <rss><channel><item>...
    items = list(root.findall(".//channel/item"))
    if not items:
        items = list(root.findall(".//{*}channel/{*}item"))
    if not items:
        return None
    item = items[0]
    title = (item.findtext("title") or item.findtext("{*}title") or "").strip()
    link = (item.findtext("link") or item.findtext("{*}link") or "").strip()
    published = (item.findtext("pubDate") or item.findtext("{*}pubDate") or "").strip()
    return {"format": "rss", "title": title, "link": link, "published": published}


async def _fetch_rss_feed(url: str) -> Dict[str, Any]:
    url = _validate_http_url(url)
    headers = {"User-Agent": "NormanChannelFeed/1.0"}
    async with httpx.AsyncClient(
        timeout=10, headers=headers, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        xml_text = resp.text
    parsed = _parse_feed_xml(xml_text)
    return {
        "source": "rss_feed",
        "url": url,
        "entry": parsed,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _random_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    kind = config.get("kind", "uniform")
    if kind == "uuid":
        import uuid

        value = str(uuid.uuid4())
    elif kind == "choice":
        options = config.get("choices") or ["alpha", "beta", "gamma"]
        value = random.choice(options)
    elif kind == "gaussian":
        mu = float(config.get("mean", 0))
        sigma = float(config.get("sigma", 1))
        value = round(random.gauss(mu, sigma), 4)
    else:
        low = float(config.get("min", 0))
        high = float(config.get("max", 100))
        value = round(random.uniform(low, high), 4)
    return {
        "kind": kind,
        "value": value,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _system_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    metrics = set(config.get("metrics") or ["load", "disk", "memory"])
    payload: Dict[str, Any] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    if "load" in metrics:
        try:
            load = os.getloadavg()
            payload["load_avg"] = {"1m": load[0], "5m": load[1], "15m": load[2]}
        except Exception:
            payload["load_avg"] = None
    if "disk" in metrics:
        payload["disk"] = _disk_usage()
    if "memory" in metrics:
        payload["memory"] = _meminfo()
    return payload


async def _post_channel_message(channel_id: int, content: str) -> None:
    db = SessionLocal()
    try:
        channel_message_crud.create(
            db, channel_id, ChannelMessageCreate(content=content)
        )
    finally:
        db.close()


async def _feed_loop(channel_id: int, config: Dict[str, Any]) -> None:
    source = config.get("source")
    interval = max(1, int(config.get("interval_seconds", 10)))
    jitter = max(0, int(config.get("jitter_seconds", 0)))
    payload_config = config.get("config") or {}
    state = FEED_STATE.setdefault(channel_id, {})
    while True:
        try:
            if source == "nist_time":
                payload = await _fetch_nist_time()
            elif source == "system_monitor":
                payload = _system_payload(payload_config)
            elif source == "http_poll":
                payload = await _fetch_http_poll(str(payload_config.get("url", "")))
            elif source == "rss_feed":
                payload = await _fetch_rss_feed(str(payload_config.get("url", "")))
            else:
                payload = _random_payload(payload_config)
            # De-dupe repeated RSS items so the channel stays useful.
            if source == "rss_feed" and isinstance(payload, dict):
                entry = payload.get("entry") or {}
                fingerprint = f"{entry.get('title', '')}|{entry.get('link', '')}"
                if fingerprint and state.get("rss_last") == fingerprint:
                    payload["note"] = "unchanged"
                state["rss_last"] = fingerprint
            await _post_channel_message(channel_id, _safe_json(payload))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _post_channel_message(
                channel_id,
                _safe_json(
                    {
                        "error": "feed_failed",
                        "source": source,
                        "detail": str(exc),
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    }
                ),
            )
        sleep_for = interval + (random.uniform(-jitter, jitter) if jitter else 0)
        await asyncio.sleep(max(1, sleep_for))


def start_feed(channel_id: int, config: Dict[str, Any]) -> Dict[str, Any]:
    stop_feed(channel_id)
    task = asyncio.create_task(_feed_loop(channel_id, config))
    FEED_TASKS[channel_id] = task
    FEED_CONFIGS[channel_id] = config
    FEED_STATE.pop(channel_id, None)
    return {"running": True, "config": config}


def stop_feed(channel_id: int) -> Dict[str, Any]:
    task = FEED_TASKS.pop(channel_id, None)
    if task:
        task.cancel()
    FEED_STATE.pop(channel_id, None)
    return {"running": False}


def feed_status(channel_id: int) -> Dict[str, Any]:
    running = channel_id in FEED_TASKS and not FEED_TASKS[channel_id].done()
    return {"running": running, "config": FEED_CONFIGS.get(channel_id)}
