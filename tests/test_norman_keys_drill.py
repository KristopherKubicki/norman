from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from app.models import SecretAlias, SecretAuditEvent, SecretPolicy, SecretProvider


def _load_drill_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "norman_keys_drill.py"
    spec = importlib.util.spec_from_file_location("norman_keys_drill", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["norman_keys_drill"] = module
    spec.loader.exec_module(module)
    return module


def test_key_revocation_drill_issues_revokes_and_masks_secret(db, tmp_path):
    drill = _load_drill_module()

    result = drill.run_key_revocation_drill(
        db,
        user_id=1,
        actor_id=1,
        secret_file=tmp_path / "drill-secret.txt",
    )

    assert result.request_status == "issued"
    assert result.lease_status == "revoked"
    assert result.issued_event_count == 1
    assert result.revoked_event_count == 1
    assert result.raw_secret_output is False

    payload = json.dumps(result.as_jsonable())
    assert drill.DRILL_SECRET_VALUE not in payload

    provider = (
        db.query(SecretProvider)
        .filter(SecretProvider.name == drill.PROVIDER_NAME)
        .one()
    )
    assert provider.kind == "file"
    assert provider.enabled is True

    alias = db.query(SecretAlias).filter(SecretAlias.name == drill.ALIAS_NAME).one()
    assert alias.provider_id == provider.id
    assert alias.lane == drill.LANE
    assert alias.allow_raw_reveal is False
    assert alias.metadata_json["contains_real_secret"] is False

    policy = db.query(SecretPolicy).filter(SecretPolicy.name == drill.POLICY_NAME).one()
    assert policy.requester_type == "agent"
    assert policy.requester_id == drill.REQUESTER_ID
    assert policy.lane == drill.LANE
    assert policy.allowed_modes == ["inject"]
    assert policy.approval_required is False
    assert policy.raw_reveal_allowed is False

    events = (
        db.query(SecretAuditEvent)
        .filter(SecretAuditEvent.lease_id == result.lease_id)
        .order_by(SecretAuditEvent.id.asc())
        .all()
    )
    assert [event.event_type for event in events] == ["lease_issued", "revoked"]
