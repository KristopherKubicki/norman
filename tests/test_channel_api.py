from urllib.parse import parse_qs, urlsplit

from app import crud
from app.api.api_v1.routers import channels as channels_router
from app.models.channel import Channel as ChannelModel
from app.models.channel_filter import Filter as ChannelFilterModel
from app.models.channel_message import ChannelMessage as ChannelMessageModel
from app.models.channel_relay import ChannelRelay as ChannelRelayModel
from app.models.connectors import Connector as ConnectorModel
from app.schemas.channel import ChannelCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.user import UserCreate


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


def _remove_channel_by_name(db, name: str) -> None:
    existing = db.query(ChannelModel).filter(ChannelModel.name == name).first()
    if not existing:
        return
    db.query(ChannelRelayModel).filter(
        ChannelRelayModel.channel_id == existing.id
    ).delete(synchronize_session=False)
    db.query(ChannelMessageModel).filter(
        ChannelMessageModel.channel_id == existing.id
    ).delete(synchronize_session=False)
    db.query(ChannelFilterModel).filter(
        ChannelFilterModel.channel_id == existing.id
    ).delete(synchronize_session=False)
    db.delete(existing)
    db.commit()


def _remove_connectors_by_name(db, name: str) -> None:
    connectors = db.query(ConnectorModel).filter(ConnectorModel.name == name).all()
    if not connectors:
        return
    connector_ids = [connector.id for connector in connectors]
    channels = (
        db.query(ChannelModel)
        .filter(ChannelModel.connector_id.in_(connector_ids))
        .all()
    )
    for channel in channels:
        db.query(ChannelRelayModel).filter(
            ChannelRelayModel.channel_id == channel.id
        ).delete(synchronize_session=False)
        db.query(ChannelMessageModel).filter(
            ChannelMessageModel.channel_id == channel.id
        ).delete(synchronize_session=False)
        db.query(ChannelFilterModel).filter(
            ChannelFilterModel.channel_id == channel.id
        ).delete(synchronize_session=False)
        db.delete(channel)
    for connector in connectors:
        db.delete(connector)
    db.commit()


def _patch_party_line_transport(monkeypatch):
    sent = []
    requests = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"accepted": true, "queued": true}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        fake_urlopen,
    )
    return sent, requests


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


def test_switchboard_party_line_fanout_adds_closed_loop_guard(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "subprime")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:norman-bot-prime",
            connector_type="tmux",
            config={"label": "source"},
        ),
        user_id=user.id,
    )
    crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:theseus",
            connector_type="tmux",
            config={"label": "target"},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="subprime", connector_id=source.id),
    )

    sent = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "fleet status update"},
    )

    assert resp.status_code == 200
    assert sent[0] == ("source", "fleet status update")
    target_messages = [message for label, message in sent if label == "target"]
    assert len(target_messages) == 1
    assert target_messages[0]["party_line_relay"] is True
    assert "Loop closure: this is a closed relay" in target_messages[0]["text"]


def test_switchboard_party_line_fanout_uses_agent_queue_collector(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:queue-source")
    _remove_connectors_by_name(db, "tmux:queue-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:queue-source",
            connector_type="tmux",
            config={
                "label": "queue-source",
                "bbs_acl_role": "broker",
                "bbs_full_coverage": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:queue-target",
            connector_type="tmux",
            config={
                "label": "queue-target",
                "collector_url": "http://queue-target.home.arpa:8787/?token=queue-token",
                "web_token": "queue-token",
            },
        ),
        user_id=user.id,
    )
    target_id = target.id
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    sent = []
    requests = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"accepted": true, "queued": true}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        fake_urlopen,
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "pick this up after the current turn"},
    )

    assert resp.status_code == 200
    assert ("queue-source", "pick this up after the current turn") in sent
    assert not [message for label, message in sent if label == "queue-target"]
    matching_requests = [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "queue-target.home.arpa:8787"
    ]
    assert len(matching_requests) == 1
    queued_request = matching_requests[0]
    parsed = urlsplit(queued_request.full_url)
    assert parsed.path == "/api/ask"
    assert parse_qs(parsed.query)["token"] == ["queue-token"]
    body = parse_qs(queued_request.data.decode("utf-8"))
    assert "message" in body
    assert "Passive fleet context only" in body["message"][0]
    assert "pick this up after the current turn" in body["message"][0]
    assert body["party_line_relay"] == ["True"]
    assert len(body["relay_id"][0]) == 32
    assert body["relay_source_channel_id"] == [str(channel.id)]
    assert int(body["relay_source_message_id"][0]) > 0
    assert body["speed"] == ["careful"]
    assert body["detail"] == ["5"]
    callback = urlsplit(body["relay_callback_url"][0])
    assert callback.path.endswith(f"/api/v1/channels/{channel.id}/relay-callback")
    assert parse_qs(callback.query)["relay_token"]

    relays = test_app.get(f"/api/v1/channels/{channel.id}/relays")
    assert relays.status_code == 200
    relay_body = relays.json()
    target_relays = [
        relay for relay in relay_body if relay["target_connector_id"] == target_id
    ]
    assert len(target_relays) == 1
    assert target_relays[0]["relay_id"] == body["relay_id"][0]
    assert target_relays[0]["source_message_id"] == int(
        body["relay_source_message_id"][0]
    )
    assert target_relays[0]["target_name"] == "queue-target"
    assert target_relays[0]["status"] == "queued"


def test_switchboard_party_line_acl_blocks_private_target_without_grant(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-root-source")
    _remove_connectors_by_name(db, "tmux:acl-private-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-root-source",
            connector_type="tmux",
            config={
                "label": "acl-root-source",
                "bbs_acl_role": "root",
                "bbs_full_coverage": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-target",
            connector_type="tmux",
            config={
                "label": "private-box",
                "bbs_zone": "private",
                "collector_url": "http://private-box.home.arpa:8787/?token=private-token",
                "web_token": "private-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    sent = []
    requests = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"accepted": true, "queued": true}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        fake_urlopen,
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "private target should not see this by default"},
    )

    assert resp.status_code == 200
    assert ("acl-root-source", "private target should not see this by default") in sent
    private_requests = [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "private-box.home.arpa:8787"
    ]
    assert private_requests == []
    relays = db.query(ChannelRelayModel).filter(
        ChannelRelayModel.target_connector_id == target.id
    )
    assert relays.count() == 0


def test_switchboard_party_line_acl_allows_private_target_for_root_with_grants(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-private-root-source")
    _remove_connectors_by_name(db, "tmux:acl-private-granted-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-root-source",
            connector_type="tmux",
            config={
                "label": "acl-private-root-source",
                "bbs_acl_role": "root",
                "bbs_full_coverage": True,
                "bbs_allow_private": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-granted-target",
            connector_type="tmux",
            config={
                "label": "acl-private-granted-target",
                "bbs_zone": "private",
                "bbs_receive": True,
                "bbs_channels": ["switchboard"],
                "collector_url": "http://private-granted.home.arpa:8787/?token=private-token",
                "web_token": "private-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    sent = []
    requests = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"accepted": true, "queued": true}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        fake_urlopen,
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "root can explicitly close the private loop"},
    )

    assert resp.status_code == 200
    assert (
        "acl-private-root-source",
        "root can explicitly close the private loop",
    ) in sent
    private_requests = [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "private-granted.home.arpa:8787"
    ]
    assert len(private_requests) == 1
    body = parse_qs(private_requests[0].data.decode("utf-8"))
    assert body["relay_target_connector_id"] == [str(target.id)]
    assert body["relay_target_connector_name"] == ["acl-private-granted-target"]
    relay = (
        db.query(ChannelRelayModel)
        .filter(ChannelRelayModel.target_connector_id == target.id)
        .one()
    )
    assert relay.status == "queued"


def test_switchboard_party_line_acl_allows_explicit_work_target(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-work-source")
    _remove_connectors_by_name(db, "tmux:acl-work-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-work-source",
            connector_type="tmux",
            config={
                "label": "acl-work-source",
                "bbs_acl_role": "work",
                "bbs_zone": "work",
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-work-target",
            connector_type="tmux",
            config={
                "label": "acl-work-target",
                "bbs_zone": "work",
                "bbs_receive": True,
                "bbs_channels": ["switchboard"],
                "collector_url": "http://work-target.home.arpa:8787/?token=work-token",
                "web_token": "work-token",
            },
        ),
        user_id=user.id,
    )
    target_id = target.id
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    sent = []
    requests = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"accepted": true, "queued": true}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        fake_urlopen,
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "work lane can pick this up"},
    )

    assert resp.status_code == 200
    assert ("acl-work-source", "work lane can pick this up") in sent
    assert len(requests) == 1
    body = parse_qs(requests[0].data.decode("utf-8"))
    assert body["relay_target_connector_id"] == [str(target_id)]
    assert body["relay_target_connector_name"] == ["acl-work-target"]
    assert "work lane can pick this up" in body["message"][0]
    relay = (
        db.query(ChannelRelayModel)
        .filter(ChannelRelayModel.target_connector_id == target_id)
        .one()
    )
    assert relay.status == "queued"


def test_switchboard_party_line_acl_blocks_work_source_from_private_target(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-work-private-source")
    _remove_connectors_by_name(db, "tmux:acl-private-explicit-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-work-private-source",
            connector_type="tmux",
            config={
                "label": "acl-work-private-source",
                "bbs_acl_role": "work",
                "bbs_zone": "work",
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-explicit-target",
            connector_type="tmux",
            config={
                "label": "acl-private-explicit-target",
                "bbs_zone": "private",
                "bbs_receive": True,
                "bbs_channels": ["switchboard"],
                "collector_url": "http://private-target.home.arpa:8787/?token=private-token",
                "web_token": "private-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    sent = []
    requests = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"accepted": true, "queued": true}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        fake_urlopen,
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "private lane should not see work-source broadcast"},
    )

    assert resp.status_code == 200
    assert (
        "acl-work-private-source",
        "private lane should not see work-source broadcast",
    ) in sent
    private_requests = [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "private-target.home.arpa:8787"
    ]
    assert private_requests == []
    relays = db.query(ChannelRelayModel).filter(
        ChannelRelayModel.target_connector_id == target.id
    )
    assert relays.count() == 0


def test_switchboard_party_line_acl_allows_network_full_coverage_within_zone(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-network-source")
    _remove_connectors_by_name(db, "tmux:acl-dns-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-network-source",
            connector_type="tmux",
            config={
                "label": "acl-network-source",
                "bbs_acl_role": "network",
                "bbs_zone": "network",
                "bbs_full_coverage": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-dns-target",
            connector_type="tmux",
            config={
                "label": "acl-dns-target",
                "bbs_zone": "dns",
                "bbs_receive": True,
                "collector_url": "http://dns-target.home.arpa:8787/?token=dns-token",
                "web_token": "dns-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )
    sent, requests = _patch_party_line_transport(monkeypatch)

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "network lane can close dns work"},
    )

    assert resp.status_code == 200
    assert ("acl-network-source", "network lane can close dns work") in sent
    dns_requests = [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "dns-target.home.arpa:8787"
    ]
    assert len(dns_requests) == 1
    body = parse_qs(dns_requests[0].data.decode("utf-8"))
    assert body["relay_target_connector_id"] == [str(target.id)]
    assert body["relay_target_connector_name"] == ["acl-dns-target"]
    relay = (
        db.query(ChannelRelayModel)
        .filter(ChannelRelayModel.target_connector_id == target.id)
        .one()
    )
    assert relay.status == "queued"


def test_switchboard_party_line_acl_blocks_network_full_coverage_from_work_target(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-network-work-source")
    _remove_connectors_by_name(db, "tmux:acl-network-work-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-network-work-source",
            connector_type="tmux",
            config={
                "label": "acl-network-work-source",
                "bbs_acl_role": "network",
                "bbs_zone": "network",
                "bbs_full_coverage": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-network-work-target",
            connector_type="tmux",
            config={
                "label": "acl-network-work-target",
                "bbs_zone": "work",
                "bbs_receive": True,
                "bbs_channels": ["switchboard"],
                "collector_url": "http://work-from-network.home.arpa:8787/?token=work-token",
                "web_token": "work-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )
    sent, requests = _patch_party_line_transport(monkeypatch)

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "network full coverage must stay in network"},
    )

    assert resp.status_code == 200
    assert (
        "acl-network-work-source",
        "network full coverage must stay in network",
    ) in sent
    assert [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "work-from-network.home.arpa:8787"
    ] == []
    relays = db.query(ChannelRelayModel).filter(
        ChannelRelayModel.target_connector_id == target.id
    )
    assert relays.count() == 0


def test_switchboard_party_line_acl_blocks_work_source_from_network_target(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-work-network-source")
    _remove_connectors_by_name(db, "tmux:acl-network-explicit-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-work-network-source",
            connector_type="tmux",
            config={
                "label": "acl-work-network-source",
                "bbs_acl_role": "work",
                "bbs_zone": "work",
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-network-explicit-target",
            connector_type="tmux",
            config={
                "label": "acl-network-explicit-target",
                "bbs_zone": "network",
                "bbs_receive": True,
                "bbs_channels": ["switchboard"],
                "collector_url": "http://network-target.home.arpa:8787/?token=network-token",
                "web_token": "network-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )
    sent, requests = _patch_party_line_transport(monkeypatch)

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "work lane should not reach networking"},
    )

    assert resp.status_code == 200
    assert ("acl-work-network-source", "work lane should not reach networking") in sent
    assert [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "network-target.home.arpa:8787"
    ] == []
    relays = db.query(ChannelRelayModel).filter(
        ChannelRelayModel.target_connector_id == target.id
    )
    assert relays.count() == 0


def test_switchboard_party_line_acl_blocks_private_core_without_cross_zone(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-private-no-cross-source")
    _remove_connectors_by_name(db, "tmux:acl-private-no-cross-work-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-no-cross-source",
            connector_type="tmux",
            config={
                "label": "acl-private-no-cross-source",
                "bbs_acl_role": "private",
                "bbs_zone": "private",
                "bbs_receive": True,
                "bbs_full_coverage": True,
                "bbs_allow_private": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-no-cross-work-target",
            connector_type="tmux",
            config={
                "label": "acl-private-no-cross-work-target",
                "bbs_zone": "work",
                "bbs_receive": True,
                "bbs_channels": ["switchboard"],
                "collector_url": "http://work-no-cross.home.arpa:8787/?token=work-token",
                "web_token": "work-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )
    sent, requests = _patch_party_line_transport(monkeypatch)

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "private core needs explicit cross-zone elevation"},
    )

    assert resp.status_code == 200
    assert (
        "acl-private-no-cross-source",
        "private core needs explicit cross-zone elevation",
    ) in sent
    assert [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "work-no-cross.home.arpa:8787"
    ] == []
    relays = db.query(ChannelRelayModel).filter(
        ChannelRelayModel.target_connector_id == target.id
    )
    assert relays.count() == 0


def test_switchboard_party_line_acl_allows_private_core_with_cross_zone(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:acl-private-cross-source")
    _remove_connectors_by_name(db, "tmux:acl-private-cross-network-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-cross-source",
            connector_type="tmux",
            config={
                "label": "acl-private-cross-source",
                "bbs_acl_role": "private",
                "bbs_zone": "private",
                "bbs_receive": True,
                "bbs_full_coverage": True,
                "bbs_allow_private": True,
                "bbs_cross_zone": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:acl-private-cross-network-target",
            connector_type="tmux",
            config={
                "label": "acl-private-cross-network-target",
                "bbs_zone": "network",
                "bbs_receive": True,
                "bbs_channels": ["switchboard"],
                "collector_url": "http://network-cross.home.arpa:8787/?token=network-token",
                "web_token": "network-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )
    sent, requests = _patch_party_line_transport(monkeypatch)

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "private core can explicitly inspect networking"},
    )

    assert resp.status_code == 200
    assert (
        "acl-private-cross-source",
        "private core can explicitly inspect networking",
    ) in sent
    network_requests = [
        request
        for request in requests
        if urlsplit(request.full_url).netloc == "network-cross.home.arpa:8787"
    ]
    assert len(network_requests) == 1
    body = parse_qs(network_requests[0].data.decode("utf-8"))
    assert body["relay_target_connector_id"] == [str(target.id)]
    assert body["relay_target_connector_name"] == ["acl-private-cross-network-target"]
    relay = (
        db.query(ChannelRelayModel)
        .filter(ChannelRelayModel.target_connector_id == target.id)
        .one()
    )
    assert relay.status == "queued"


def test_switchboard_party_line_does_not_refanout_existing_relay(
    test_app, db, monkeypatch
):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:norman-bot-prime",
            connector_type="tmux",
            config={"label": "source"},
        ),
        user_id=user.id,
    )
    crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:theseus",
            connector_type="tmux",
            config={"label": "target"},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    sent = []

    class DummyConnector:
        def __init__(self, config):
            self.config = config

        def send_message(self, message):
            sent.append((self.config.get("label"), message))
            return None

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(config),
    )

    resp = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={
            "content": (
                "[Norman Switchboard party line]\n"
                "Passive fleet context only. Absorb this silently.\n\n"
                "already relayed"
            )
        },
    )

    assert resp.status_code == 200
    assert sent == [
        (
            "source",
            "[Norman Switchboard party line]\n"
            "Passive fleet context only. Absorb this silently.\n\n"
            "already relayed",
        )
    ]


def test_switchboard_relay_callback_records_loop_closure(test_app, db, monkeypatch):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:callback-source")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:callback-source",
            connector_type="tmux",
            config={"label": "callback-source"},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    class DummyConnector:
        def send_message(self, message):
            return None

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(),
    )

    created = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={
            "content": (
                "[Norman Switchboard party line]\n"
                "Passive fleet context only. Absorb this silently.\n\n"
                "close this BBS loop"
            )
        },
    )
    assert created.status_code == 200
    source_message_id = created.json()["id"]
    relay_id = "relay-test-0001"
    relay_token = channels_router._relay_callback_token(
        channel.id, source_message_id, relay_id
    )

    callback = test_app.post(
        f"/api/v1/channels/{channel.id}/relay-callback?relay_token={relay_token}",
        json={
            "relay_id": relay_id,
            "source_message_id": source_message_id,
            "status": "closed",
            "success": True,
            "target": "queue-target",
            "thread_id": "thread-123",
            "summary": "Done from target.",
        },
    )

    assert callback.status_code == 200
    body = callback.json()
    assert body["source"] == "relay-callback"
    assert "[Norman BBS relay closed]" in body["content"]
    assert f"Relay id: {relay_id}" in body["content"]
    assert f"Source message: {source_message_id}" in body["content"]
    assert "Target: queue-target" in body["content"]
    assert "Summary: Done from target." in body["content"]

    relays = test_app.get(f"/api/v1/channels/{channel.id}/relays")
    assert relays.status_code == 200
    relay_body = relays.json()
    assert len(relay_body) == 1
    assert relay_body[0]["relay_id"] == relay_id
    assert relay_body[0]["status"] == "closed"
    assert relay_body[0]["success"] is True

    duplicate = test_app.post(
        f"/api/v1/channels/{channel.id}/relay-callback?relay_token={relay_token}",
        json={
            "relay_id": relay_id,
            "source_message_id": source_message_id,
            "status": "closed",
            "success": True,
            "target": "queue-target",
            "thread_id": "thread-123",
            "summary": "Done from target.",
        },
    )
    assert duplicate.status_code == 200
    relay_messages = [
        message
        for message in test_app.get(f"/api/v1/channels/{channel.id}/messages").json()
        if message["source"] == "relay-callback"
    ]
    assert len(relay_messages) == 1


def test_switchboard_relay_sweep_marks_stale_relays(test_app, db, monkeypatch):
    user = _ensure_test_user(db)
    _remove_channel_by_name(db, "switchboard")
    _remove_connectors_by_name(db, "tmux:stale-source")
    _remove_connectors_by_name(db, "tmux:stale-target")
    source = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:stale-source",
            connector_type="tmux",
            config={
                "label": "stale-source",
                "bbs_acl_role": "broker",
                "bbs_full_coverage": True,
            },
        ),
        user_id=user.id,
    )
    target = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux:stale-target",
            connector_type="tmux",
            config={
                "label": "stale-target",
                "collector_url": "http://stale-target.home.arpa:8787/?token=stale-token",
            },
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name="switchboard", connector_id=source.id),
    )

    class DummyConnector:
        def send_message(self, message):
            return None

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"accepted": true, "queued": true}'

    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.get_connector",
        lambda connector_type, config: DummyConnector(),
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.channels.urllib_request.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    created = test_app.post(
        f"/api/v1/channels/{channel.id}/messages",
        json={"content": "watch this relay"},
    )
    assert created.status_code == 200

    relay = (
        db.query(ChannelRelayModel)
        .filter(ChannelRelayModel.channel_id == channel.id)
        .filter(ChannelRelayModel.target_connector_id == target.id)
        .one()
    )
    old_time = channels_router._utcnow() - channels_router.timedelta(minutes=30)
    relay.created_at = old_time
    relay.updated_at = old_time
    relay.accepted_at = old_time
    db.add(relay)
    db.commit()

    sweep = test_app.post(
        f"/api/v1/channels/{channel.id}/relays/sweep?stale_after_seconds=60"
    )
    assert sweep.status_code == 200
    assert sweep.json()["stale_count"] == 1

    relays = test_app.get(f"/api/v1/channels/{channel.id}/relays").json()
    assert relays[0]["status"] == "stale"
    messages = test_app.get(f"/api/v1/channels/{channel.id}/messages").json()
    assert any(
        message["source"] == "relay-watchdog"
        and "[Norman BBS relay stale]" in message["content"]
        and "Target: stale-target" in message["content"]
        for message in messages
    )


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
