def test_bridge_conversations_create_rooms_and_reuse_direct_messages(test_app):
    direct_payload = {
        "kind": "direct",
        "title": "Panel Bot",
        "principal_slug": "work",
        "domain_slug": "product",
        "direct_agent_slug": "panel-bot",
        "member_slugs": ["panel-bot"],
    }
    first_direct = test_app.post("/api/v1/bridge/conversations", json=direct_payload)
    second_direct = test_app.post("/api/v1/bridge/conversations", json=direct_payload)
    room = test_app.post(
        "/api/v1/bridge/conversations",
        json={
            "kind": "room",
            "title": "Launch room",
            "principal_slug": "work",
            "domain_slug": "product",
            "member_slugs": ["panel-bot", "research-bot", "panel-bot"],
        },
    )

    assert first_direct.status_code == 201
    assert second_direct.status_code == 201
    assert (
        first_direct.json()["conversation_id"]
        == second_direct.json()["conversation_id"]
    )
    assert room.status_code == 201
    assert room.json()["member_slugs"] == ["panel-bot", "research-bot"]

    listed = test_app.get("/api/v1/bridge/conversations")
    assert listed.status_code == 200
    ids = {item["conversation_id"] for item in listed.json()["items"]}
    assert first_direct.json()["conversation_id"] in ids
    assert room.json()["conversation_id"] in ids


def test_bridge_room_members_can_be_updated_and_room_deleted(test_app):
    created = test_app.post(
        "/api/v1/bridge/conversations",
        json={
            "kind": "room",
            "title": "Operations",
            "principal_slug": "shared",
            "member_slugs": ["netops"],
        },
    )
    conversation_id = created.json()["conversation_id"]

    updated = test_app.request(
        "PATCH",
        f"/api/v1/bridge/conversations/{conversation_id}",
        json={"title": "Infrastructure", "member_slugs": ["netops", "uplink"]},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Infrastructure"
    assert updated.json()["member_slugs"] == ["netops", "uplink"]

    deleted = test_app.delete(f"/api/v1/bridge/conversations/{conversation_id}")
    assert deleted.status_code == 204
    missing = test_app.request(
        "PATCH",
        f"/api/v1/bridge/conversations/{conversation_id}",
        json={"title": "Missing"},
    )
    assert missing.status_code == 404


def test_bridge_direct_message_loads_managed_station_history(test_app, db, monkeypatch):
    user_id = test_app.get("/api/v1/users/me").json()["id"]
    db.add(
        Connector(
            user_id=user_id,
            name="tmux:artmonster",
            connector_type="tmux",
            config={
                "session": "artmonster",
                "web_url": "http://artmonster.internal:8797",
                "web_token": "station-secret",
            },
        )
    )
    db.commit()

    captured = {}

    def fake_history(web_url, *, access_token="", limit=100, timeout=4.0):
        captured.update(
            web_url=web_url,
            access_token=access_token,
            limit=limit,
        )
        return {
            "reachable": True,
            "agent_name": "Artmonster",
            "thread_id": "thread-1",
            "items": [
                {
                    "turn_id": "turn-1",
                    "prompt": "Make the mark larger.",
                    "response": "Updated the composition.",
                    "started_at": 1787212800,
                    "finished_at": 1787212860,
                }
            ],
        }

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations.fetch_console_history",
        fake_history,
    )
    response = test_app.get(
        "/api/v1/bridge/conversations/agents/artmonster/history?limit=40"
    )

    assert response.status_code == 200
    assert response.json()["thread_id"] == "thread-1"
    assert response.json()["items"][0]["prompt"] == "Make the mark larger."
    assert captured == {
        "web_url": "http://artmonster.internal:8797",
        "access_token": "station-secret",
        "limit": 40,
    }


def test_bridge_eyebat_alias_uses_glimpser_station(test_app, monkeypatch):
    captured = {}

    def fake_estate_history_url(_db, agent_slug):
        captured["estate_slug"] = agent_slug
        return "http://glimpser.internal:8788"

    def fake_history(web_url, *, access_token="", limit=100, timeout=4.0):
        captured.update(web_url=web_url, access_token=access_token, limit=limit)
        return {"reachable": True, "agent_name": "Glimpser", "items": []}

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._estate_history_url",
        fake_estate_history_url,
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations.fetch_console_history",
        fake_history,
    )
    response = test_app.get(
        "/api/v1/bridge/conversations/agents/eyebat/history?limit=40"
    )

    assert response.status_code == 200
    assert response.json()["agent_slug"] == "eyebat"
    assert captured == {
        "estate_slug": "glimpser",
        "web_url": "http://glimpser.internal:8788",
        "access_token": "",
        "limit": 40,
    }


def test_bridge_history_uses_shared_frontdoor_for_unregistered_station(
    test_app, monkeypatch
):
    captured = {}

    def fake_history(web_url, *, access_token="", limit=100, timeout=4.0):
        captured.update(web_url=web_url, access_token=access_token, limit=limit)
        return {"reachable": True, "agent_name": "Artmonster", "items": []}

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations.fetch_console_history",
        fake_history,
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._history_connector",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._estate_history_url",
        lambda *_args: "",
    )
    response = test_app.get(
        "/api/v1/bridge/conversations/agents/artmonster/history?limit=40"
    )

    assert response.status_code == 200
    assert captured == {
        "web_url": "https://norman.home.arpa/bot/artmonster/",
        "access_token": "",
        "limit": 40,
    }


def test_bridge_aliases_use_shared_canonical_station_names(test_app, monkeypatch):
    captured = []

    def fake_history(web_url, *, access_token="", limit=100, timeout=4.0):
        captured.append(web_url)
        return {"reachable": True, "items": []}

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations.fetch_console_history",
        fake_history,
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._history_connector",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._estate_history_url",
        lambda *_args: "",
    )

    for slug in ("eyebat", "keystone", "netops"):
        response = test_app.get(f"/api/v1/bridge/conversations/agents/{slug}/history")
        assert response.status_code == 200

    assert captured == [
        "https://norman.home.arpa/bot/glimpser/",
        "https://norman.home.arpa/bot/compere/",
        "https://norman.home.arpa/bot/networking/",
    ]


def test_bridge_rejects_non_conversational_estate_surfaces(test_app):
    response = test_app.get("/api/v1/bridge/conversations/agents/dohio/history")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This estate surface does not support Bridge direct messages"
    )


def test_bridge_history_omits_legacy_diagnostics(test_app, db, monkeypatch):
    user_id = test_app.get("/api/v1/users/me").json()["id"]
    db.add(
        Connector(
            user_id=user_id,
            name="tmux:artmonster",
            connector_type="tmux",
            config={
                "session": "artmonster",
                "web_url": "http://artmonster.internal:8797",
            },
        )
    )
    db.commit()

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations.fetch_console_history",
        lambda *_args, **_kwargs: {
            "reachable": True,
            "items": [
                {
                    "turn_id": "legacy-status",
                    "prompt": "quick status",
                    "response": "- State: idle\n- Selected route: codex/gpt-5.4\n- Local proof: timeout",
                },
                {
                    "turn_id": "real-turn",
                    "prompt": "show the newest image",
                    "response": "I found the latest image attachment.",
                },
            ],
        },
    )

    response = test_app.get("/api/v1/bridge/conversations/agents/artmonster/history")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "turn_id": "real-turn",
            "prompt": "show the newest image",
            "response": "I found the latest image attachment.",
        }
    ]


def test_bridge_direct_message_submits_to_managed_station(test_app, db, monkeypatch):
    user_id = test_app.get("/api/v1/users/me").json()["id"]
    db.add(
        Connector(
            user_id=user_id,
            name="tmux:artmonster",
            connector_type="tmux",
            config={
                "session": "artmonster",
                "web_url": "http://artmonster.internal:8797",
                "web_token": "station-secret",
            },
        )
    )
    db.commit()
    conversation = test_app.post(
        "/api/v1/bridge/conversations",
        json={
            "kind": "direct",
            "principal_slug": "personal",
            "direct_agent_slug": "artmonster",
            "member_slugs": ["artmonster"],
        },
    ).json()
    captured = {}

    def fake_submit(web_url, *, access_token, message, submission_id):
        captured.update(
            web_url=web_url,
            access_token=access_token,
            message=message,
            submission_id=submission_id,
        )
        return {"accepted": True, "running": True, "submission_state": "running"}

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._submit_station_prompt",
        fake_submit,
    )
    response = test_app.post(
        "/api/v1/bridge/conversations/agents/artmonster/messages",
        json={
            "message": "Show the newest art.",
            "conversation_id": conversation["conversation_id"],
            "submission_id": "bridge-test",
        },
    )
    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert captured == {
        "web_url": "http://artmonster.internal:8797",
        "access_token": "station-secret",
        "message": "Show the newest art.",
        "submission_id": "bridge-test",
    }


def test_bridge_direct_message_preserves_station_admission_denial(
    test_app, monkeypatch
):
    from app.api.api_v1.routers.bridge_conversations import StationRequestError

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._submit_station_prompt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            StationRequestError(
                "This thread exceeded its reauthorization token limit.",
                status_code=409,
            )
        ),
    )

    response = test_app.post(
        "/api/v1/bridge/conversations/agents/eyebat/messages",
        json={"message": "What is the CPU load right now?"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This thread exceeded its reauthorization token limit."
    )


def test_bridge_station_media_is_validated_against_history_and_proxied(
    test_app, db, monkeypatch
):
    user_id = test_app.get("/api/v1/users/me").json()["id"]
    db.add(
        Connector(
            user_id=user_id,
            name="tmux:artmonster",
            connector_type="tmux",
            config={
                "session": "artmonster",
                "web_url": "http://artmonster.internal:8797",
                "web_token": "station-secret",
            },
        )
    )
    db.commit()

    def fake_history(web_url, *, access_token="", limit=100, timeout=4.0):
        return {
            "reachable": True,
            "items": [
                {
                    "turn_id": "turn-1",
                    "attachments": [
                        {
                            "token": "asset-1",
                            "name": "latest-art.png",
                            "path": "/srv/art/latest-art.png",
                            "content_type": "image/png",
                            "kind": "image",
                        }
                    ],
                }
            ],
        }

    captured = {}

    def fake_file(web_url, *, access_token, path, max_bytes=32 * 1024 * 1024):
        captured.update(
            web_url=web_url,
            access_token=access_token,
            path=path,
        )
        return b"PNG", "image/png"

    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations.fetch_console_history",
        fake_history,
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.bridge_conversations._fetch_station_file",
        fake_file,
    )

    response = test_app.get(
        "/api/v1/bridge/conversations/agents/artmonster/media/asset-1"
    )

    assert response.status_code == 200
    assert response.content == b"PNG"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == (
        'inline; filename="latest-art.png"'
    )
    assert captured == {
        "web_url": "http://artmonster.internal:8797",
        "access_token": "station-secret",
        "path": "/srv/art/latest-art.png",
    }

    download = test_app.get(
        "/api/v1/bridge/conversations/agents/artmonster/media/asset-1?download=1"
    )
    assert download.status_code == 200
    assert download.headers["content-disposition"] == (
        'attachment; filename="latest-art.png"'
    )

    missing = test_app.get(
        "/api/v1/bridge/conversations/agents/artmonster/media/not-real"
    )
    assert missing.status_code == 404


from app.models import Connector
