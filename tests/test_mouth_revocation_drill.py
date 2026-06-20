from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.config import settings
from app.models import RoutingEvent, RoutingJob


def _load_drill_module():
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "mouth_revocation_drill.py"
    )
    spec = importlib.util.spec_from_file_location("mouth_revocation_drill", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mouth_revocation_drill"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_mouth_revocation_drill_blocks_then_restores_queueing(db):
    drill = _load_drill_module()
    previous_level = int(getattr(settings, "safety_kill_switch_level", 0))
    settings.safety_kill_switch_level = 0

    try:
        result = await drill.run_mouth_revocation_drill(
            db,
            profile="shared",
            run_id="unit-test",
        )
    finally:
        settings.safety_kill_switch_level = previous_level

    assert result.previous_kill_switch_level == 0
    assert result.restored_kill_switch_level == 0
    assert result.external_send_attempted is False
    assert result.parked_job_count == 1

    blocked_event = (
        db.query(RoutingEvent).filter(RoutingEvent.id == result.blocked_event_id).one()
    )
    assert blocked_event.status == "logged"
    assert blocked_event.delivery_status == "disabled"
    assert "kill-switch" in blocked_event.delivery_error
    assert (
        db.query(RoutingJob)
        .filter(RoutingJob.event_id == result.blocked_event_id)
        .count()
        == 0
    )

    restored_event = (
        db.query(RoutingEvent).filter(RoutingEvent.id == result.restored_event_id).one()
    )
    assert restored_event.status == "queued"
    assert restored_event.delivery_status == "queued"
    restored_job = (
        db.query(RoutingJob)
        .filter(RoutingJob.event_id == result.restored_event_id)
        .one()
    )
    assert restored_job.status == "done"
    assert restored_job.last_error == "Mouth drill parked before delivery"
