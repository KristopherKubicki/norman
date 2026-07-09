from __future__ import annotations

import json
from typing import Iterable

from app.services.console_runtime.events import ConsoleRuntimeEvent


def event_to_sse(event: ConsoleRuntimeEvent) -> str:
    payload = json.dumps(event.as_dict(), sort_keys=True, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"


def events_to_sse(events: Iterable[ConsoleRuntimeEvent]) -> str:
    return "".join(event_to_sse(event) for event in events)
