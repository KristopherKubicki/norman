from app import crud
from app.schemas.channel import ChannelCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.user import UserCreate
from urllib.parse import parse_qs, urlsplit


def _ensure_test_user(db):
    user = crud.user.get_user_by_email(db, "test@example.com")
    if user:
        return user
    return crud.user.create_user(
        db,
        user=UserCreate(
            email="test@example.com",
            username="test_user",
            password="pass123",
        ),
    )


def _ensure_named_test_user(db, email: str):
    user = crud.user.get_user_by_email(db, email)
    if user:
        return user
    username = email.split("@", 1)[0]
    return crud.user.create_user(
        db,
        user=UserCreate(
            email=email,
            username=username,
            password="pass123",
        ),
    )


def _patch_subprime_registry(monkeypatch):
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.estate_sync.load_runtime_registry",
        lambda path=None: {
            "services": [
                {
                    "slug": "norman-service",
                    "display_name": "Norman Prime",
                    "principal": "kristopher",
                    "domain": "kristopher-knowledge",
                    "worker": "norman-host",
                    "console_url": "https://norman.home.arpa/codex/",
                },
                {
                    "slug": "housebot",
                    "display_name": "Housebot",
                    "principal": "kristopher",
                    "domain": "kristopher-household",
                    "worker": "toy-box",
                    "console_url": "https://housebot.home.arpa/",
                },
                {
                    "slug": "glimpser",
                    "display_name": "Glimpser",
                    "principal": "kristopher",
                    "domain": "kristopher-observability",
                    "worker": "toy-box",
                    "console_url": "https://eyebat.home.arpa/",
                },
                {
                    "slug": "autocamera",
                    "display_name": "Autocamera",
                    "principal": "kristopher",
                    "domain": "kristopher-observability",
                    "worker": "hal",
                    "console_url": "https://autocamera.home.arpa/",
                },
                {
                    "slug": "control-plane",
                    "display_name": "Control Plane",
                    "principal": "openbrand",
                    "domain": "openbrand-ops",
                    "worker": "openbrand-work-service-node",
                    "console_url": "https://cp.kris.openbrand.com/",
                },
                {
                    "slug": "panelbot",
                    "display_name": "Panelbot",
                    "principal": "openbrand",
                    "domain": "openbrand-ops",
                    "worker": "openbrand-work-service-node",
                    "console_url": "https://panelbot.kris.openbrand.com/",
                },
                {
                    "slug": "parkergale",
                    "display_name": "PEFB",
                    "principal": "parkergale",
                    "domain": "parkergale-private",
                    "worker": "private-host",
                    "console_url": "https://pefb.home.arpa/",
                },
                {
                    "slug": "mls",
                    "display_name": "MLS",
                    "principal": "kristopher",
                    "domain": "kristopher-household",
                    "worker": "openbrand-work-service-node",
                    "console_url": "https://mls.kris.openbrand.com/",
                },
            ]
        },
    )


def test_channel_message_endpoint_delivers_via_connector(test_app, db, monkeypatch):
    user = _ensure_test_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="sample-channel-send",
            connector_type="sample",
            config={},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="sample-channel-send", connector_id=connector.id),
    )

    sent = {}

    class DummyConnector:
        def send_message(self, message):
            sent["message"] = message
            return None

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "hello channel"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "hello channel"
    assert sent["message"] == "hello channel"


def test_channel_message_endpoint_allows_manual_send_during_manual_mode(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="manual-channel-send",
            connector_type="sample",
            config={},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="manual-channel-send", connector_id=connector.id),
    )
    connector.config = {
        "channel_operator_modes": {str(channel.id): {"mode": "take", "note": "manual"}}
    }
    db.add(connector)
    db.commit()
    db.refresh(connector)

    sent = {}

    class DummyConnector:
        def send_message(self, message):
            sent["message"] = message
            return None

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "hello manual"},
    )
    assert resp.status_code == 200
    assert sent["message"] == "hello manual"


def test_channel_message_endpoint_uses_structured_payload_for_dict_connectors(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="dict-channel-send",
            connector_type="sample",
            config={},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="dict-channel-send", connector_id=connector.id),
    )

    sent = {}

    class DummyConnector:
        def send_message(self, message: dict):
            sent["message"] = message
            return None

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "hello dict"},
    )
    assert resp.status_code == 200
    assert sent["message"]["text"] == "hello dict"
    assert sent["message"]["channel_id"] == channel.id
    assert sent["message"]["channel_name"] == channel.name


def test_channel_message_endpoint_returns_error_when_connector_send_fails(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="failing-channel-send",
            connector_type="sample",
            config={},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="failing-channel-send", connector_id=connector.id),
    )

    class DummyConnector:
        def send_message(self, message):
            raise RuntimeError("send failed")

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "hello fail"},
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "send failed"

    resp = test_app.get(f"/api/v1/channels/{channel.id}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


def test_channel_operator_endpoint_updates_connector_and_channel_payload(test_app, db):
    user = _ensure_test_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="channel-operator",
            connector_type="sample",
            config={},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="channel-operator", connector_id=connector.id),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/operator",
        json={"mode": "shared", "note": "shared drafting"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["operator_mode"] == "co_pilot"
    assert payload["operator_note"] == "shared drafting"

    refreshed = crud.connector.get(db, connector.id)
    states = (refreshed.config or {}).get("channel_operator_modes") or {}
    assert states[str(channel.id)]["mode"] == "co_pilot"
    assert states[str(channel.id)]["note"] == "shared drafting"

    resp = test_app.get(f"/api/v1/channels/{channel.id}")
    assert resp.status_code == 200
    channel_payload = resp.json()
    assert channel_payload["operator_mode"] == "co_pilot"
    assert channel_payload["operator_note"] == "shared drafting"


def test_subprime_channel_message_fanout_reaches_tmux_fleet(test_app, db, monkeypatch):
    _patch_subprime_registry(monkeypatch)
    user = _ensure_test_user(db)
    subprime_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:subprime-fanout",
            connector_type="tmux",
            config={"marker": "tmux:subprime", "session_name": "subprime"},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="Subprime", connector_id=subprime_connector.id),
    )
    housebot_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:housebot-fanout",
            connector_type="tmux",
            config={"marker": "tmux:housebot", "session_name": "housebot"},
        ),
        user_id=user.id,
    )
    control_plane_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:control-plane-fanout",
            connector_type="tmux",
            config={"marker": "tmux:control_plane", "session_name": "control_plane"},
        ),
        user_id=user.id,
    )
    logs_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:logs-fanout",
            connector_type="tmux",
            config={"marker": "tmux:logs", "session_name": "logs"},
        ),
        user_id=user.id,
    )
    sample_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="sample-out-of-band",
            connector_type="sample",
            config={"marker": "sample"},
        ),
        user_id=user.id,
    )
    assert housebot_connector.id
    assert control_plane_connector.id
    assert logs_connector.id
    assert sample_connector.id

    sent: dict[str, list[object]] = {}

    class DummyConnector:
        def __init__(self, marker):
            self.marker = marker

        def send_message(self, message):
            sent.setdefault(self.marker, []).append(message)
            return None

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(
            (config or {}).get("marker", connector_type)
        ),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "share this with the fleet"},
    )
    assert resp.status_code == 200
    assert sent["tmux:subprime"] == ["share this with the fleet"]
    assert len(sent["tmux:housebot"]) == 1
    assert len(sent["tmux:control_plane"]) == 1
    assert "tmux:logs" not in sent
    assert "sample" not in sent
    assert sent["tmux:housebot"][0]["submit_mode"] == "tab_enter"
    assert "Norman Subprime party line" in sent["tmux:housebot"][0]["text"]
    assert "share this with the fleet" in sent["tmux:housebot"][0]["text"]


def test_subprime_channel_message_fanout_prefers_tmux_collectors(
    test_app, db, monkeypatch
):
    _patch_subprime_registry(monkeypatch)
    user = _ensure_test_user(db)
    subprime_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:subprime-collectors",
            connector_type="tmux",
            config={"marker": "tmux:subprime", "session_name": "subprime"},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(
            name="Console - Subprime", connector_id=subprime_connector.id
        ),
    )
    housebot_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:housebot-collectors",
            connector_type="tmux",
            config={
                "collector_url": "https://housebot.home.arpa/?token=housebot-token",
                "web_token": "housebot-token",
                "session_name": "housebot",
            },
        ),
        user_id=user.id,
    )
    control_plane_connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:control-plane-collectors",
            connector_type="tmux",
            config={
                "collector_url": "https://cp.kris.openbrand.com/?token=cp-token",
                "web_token": "cp-token",
                "session_name": "control_plane",
            },
        ),
        user_id=user.id,
    )
    assert housebot_connector.id
    assert control_plane_connector.id

    sent: dict[str, list[object]] = {}
    requests: list[dict[str, str]] = []

    class DummyConnector:
        def __init__(self, marker):
            self.marker = marker

        def send_message(self, message):
            sent.setdefault(self.marker, []).append(message)
            return None

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            import json

            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(request, timeout=0):
        requests.append(
            {
                "url": request.full_url,
                "body": request.data.decode("utf-8"),
                "timeout": str(timeout),
            }
        )
        return _Resp({"accepted": True, "snapshot": {}})

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(
            (config or {}).get("marker", connector_type)
        ),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels._subprime_party_line_targets",
        lambda db, user_id, source_connector_id: [
            housebot_connector,
            control_plane_connector,
        ],
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        _fake_urlopen,
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "share this with the fleet"},
    )
    assert resp.status_code == 200
    assert sent["tmux:subprime"] == ["share this with the fleet"]
    assert len(requests) == 2
    assert {urlsplit(item["url"]).netloc for item in requests} == {
        "housebot.home.arpa",
        "cp.kris.openbrand.com",
    }
    for item in requests:
        params = parse_qs(urlsplit(item["url"]).query)
        body = parse_qs(item["body"])
        assert "token" in params
        assert "message" in body
        assert "Norman Subprime party line" in body["message"][0]
        assert "share this with the fleet" in body["message"][0]


def test_subprime_targets_limit_home_ops_to_home_cluster_and_norman(
    test_app, db, monkeypatch
):
    _patch_subprime_registry(monkeypatch)
    user = _ensure_named_test_user(db, "subprime-home-ops@example.com")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:housebot",
            connector_type="tmux",
            config={"marker": "tmux:housebot"},
        ),
        user_id=user.id,
    )
    glimpser = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:glimpser",
            connector_type="tmux",
            config={"marker": "tmux:glimpser"},
        ),
        user_id=user.id,
    )
    autocamera = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:autocamera",
            connector_type="tmux",
            config={"marker": "tmux:autocamera"},
        ),
        user_id=user.id,
    )
    norman = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:norman",
            connector_type="tmux",
            config={"marker": "tmux:norman"},
        ),
        user_id=user.id,
    )
    control_plane = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:control_plane",
            connector_type="tmux",
            config={"marker": "tmux:control_plane"},
        ),
        user_id=user.id,
    )
    parkergale = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:parkergale",
            connector_type="tmux",
            config={"marker": "tmux:parkergale"},
        ),
        user_id=user.id,
    )

    from app.api.api_v1.routers.channels import _subprime_party_line_targets

    targets = _subprime_party_line_targets(db, user.id, source.id)
    target_ids = {item.id for item in targets}

    assert target_ids == {glimpser.id, autocamera.id, norman.id}
    assert control_plane.id not in target_ids
    assert parkergale.id not in target_ids


def test_subprime_targets_limit_work_lane_to_work_and_norman(test_app, db, monkeypatch):
    _patch_subprime_registry(monkeypatch)
    user = _ensure_named_test_user(db, "subprime-work@example.com")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:control_plane",
            connector_type="tmux",
            config={"marker": "tmux:control_plane"},
        ),
        user_id=user.id,
    )
    panelbot = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:panelbot",
            connector_type="tmux",
            config={"marker": "tmux:panelbot"},
        ),
        user_id=user.id,
    )
    housebot = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:housebot",
            connector_type="tmux",
            config={"marker": "tmux:housebot"},
        ),
        user_id=user.id,
    )
    mls = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:mls",
            connector_type="tmux",
            config={"marker": "tmux:mls"},
        ),
        user_id=user.id,
    )
    norman = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:subprime",
            connector_type="tmux",
            config={"marker": "tmux:subprime"},
        ),
        user_id=user.id,
    )

    from app.api.api_v1.routers.channels import _subprime_party_line_targets

    targets = _subprime_party_line_targets(db, user.id, source.id)
    target_ids = {item.id for item in targets}

    assert target_ids == {panelbot.id, norman.id}
    assert housebot.id not in target_ids
    assert mls.id not in target_ids


def test_subprime_targets_limit_private_lane_to_norman_only(test_app, db, monkeypatch):
    _patch_subprime_registry(monkeypatch)
    user = _ensure_named_test_user(db, "subprime-private@example.com")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:parkergale",
            connector_type="tmux",
            config={"marker": "tmux:parkergale"},
        ),
        user_id=user.id,
    )
    housebot = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:housebot",
            connector_type="tmux",
            config={"marker": "tmux:housebot"},
        ),
        user_id=user.id,
    )
    control_plane = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:control_plane",
            connector_type="tmux",
            config={"marker": "tmux:control_plane"},
        ),
        user_id=user.id,
    )
    norman = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:norman",
            connector_type="tmux",
            config={"marker": "tmux:norman"},
        ),
        user_id=user.id,
    )

    from app.api.api_v1.routers.channels import _subprime_party_line_targets

    targets = _subprime_party_line_targets(db, user.id, source.id)
    target_ids = {item.id for item in targets}

    assert target_ids == {norman.id}
    assert housebot.id not in target_ids
    assert control_plane.id not in target_ids
