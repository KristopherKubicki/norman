import json
import importlib.util
import pathlib
import sys
import uuid
from types import SimpleNamespace


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_SCRIPT_PATH = REPO_ROOT / "scripts" / "norman_codex_web.py"
LAUNCH_SCRIPT_PATH = REPO_ROOT / "scripts" / "norman_codex_launch.sh"


def _load_norman_codex_web(monkeypatch, tmp_path, **overrides):
    codex_home = tmp_path / "codex-home"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("HOUSEBOT_CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("HOUSEBOT_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HOUSEBOT_CODEX_MODEL", "gpt-5.4")
    monkeypatch.setenv("HOUSEBOT_CODEX_LATEST_MODEL", "gpt-5.5")
    monkeypatch.setenv("HOUSEBOT_CODEX_AVAILABLE_MODELS", "gpt-5.4,gpt-5.5")
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)

    module_name = f"norman_codex_web_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, WEB_SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _cheap_snapshot(module):
    meta = module.load_status_meta()
    queued = module.normalize_queue(meta.get("queued_prompts"))
    return {
        "pending": bool(meta.get("pending")),
        "state": str(meta.get("state") or ""),
        "status_message": str(meta.get("status_message") or ""),
        "queued_prompts": queued,
        "queue_depth": len(queued),
        "running_prompt": str(meta.get("running_prompt") or ""),
    }


def test_runtime_model_defaults_to_configured_env(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    assert module.AVAILABLE_MODELS == ["gpt-5.4", "gpt-5.5"]
    assert module.configured_chat_model() == "gpt-5.4"
    assert module.chat_model_update_available() is True


def test_careful_response_speed_uses_xhigh_reasoning(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    assert module.response_reasoning_effort("careful") == "xhigh"


def test_ensure_session_does_not_wait_when_service_start_fails(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    sleeps = []
    commands = []

    monkeypatch.setattr(module, "session_exists", lambda: False)
    monkeypatch.setattr(
        module,
        "run",
        lambda cmd, input_text=None, check=False: commands.append(cmd)
        or SimpleNamespace(returncode=1, stdout="", stderr="Access denied"),
    )
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert module.ensure_session() is False
    assert commands == [["systemctl", "start", module.CODEX_SERVICE]]
    assert sleeps == []


def test_busy_web_prompt_queues_operator_prompt_with_visible_position(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        running_speed="balanced",
        running_detail=3,
    )
    module.ACTIVE_PROMPT_THREAD = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    accepted, snapshot = module.start_web_prompt("status?", "fast", 2, [])

    assert accepted is True
    assert snapshot["pending"] is True
    queued = module.normalize_queue(module.load_status_meta()["queued_prompts"])
    assert len(queued) == 1
    assert queued[0]["prompt"] == "status?"
    assert queued[0]["source"] == "operator"
    assert queued[0]["speed"] == "fast"
    assert queued[0]["detail"] == 2
    meta = module.load_status_meta()
    assert "position 1" in meta["last_action_detail"]
    assert "Current web reply is still running" in meta["status_message"]

    module.ACTIVE_PROMPT_THREAD = None


def test_recover_stale_prompt_state_marks_queue_stale_without_autolaunch(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Working.",
        running_prompt="unfinished recovered prompt",
        running_speed="careful",
        running_detail=5,
        running_attachments=[],
        last_started_at=123,
        queued_prompts=[
            {
                "prompt": "Passive fleet context only. Older BBS item.",
                "queued_at": 124,
                "source": "passive",
            }
        ],
    )
    launches = []
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(
        module, "launch_prompt_worker", lambda *args: launches.append(args)
    )

    module.recover_stale_prompt_state()

    meta = module.load_status_meta()
    queue = module.normalize_queue(meta["queued_prompts"])
    assert meta["pending"] is False
    assert meta["state"] == "recovered"
    assert meta["recovered_after_restart"] is True
    assert meta["stale_queue"] is True
    assert "Review the queue before resuming" in meta["status_message"]
    assert queue[0]["prompt"] == "unfinished recovered prompt"
    assert queue[0]["source"] == "recovered"
    assert queue[0]["recovered"] is True
    assert queue[1]["source"] == "passive"
    assert launches == []


def test_cancel_active_web_prompt_targets_tracked_codex_process_group(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Working.",
        running_prompt="cancel this",
        active_child_pid=12345,
        active_child_pgid=12345,
        queued_prompts=[{"prompt": "queued follow-up", "source": "operator"}],
    )
    terminations = []
    monkeypatch.setattr(
        module,
        "terminate_process_group",
        lambda pid, pgid: terminations.append((pid, pgid)) or True,
    )
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: True)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    snapshot = module.cancel_active_web_prompt(clear_queue=True)

    assert terminations == [(12345, 12345)]
    assert snapshot["queue_depth"] == 0
    meta = module.load_status_meta()
    assert meta["state"] == "cancelling"
    assert meta["cancel_requested_at"] > 0
    assert meta["queued_prompts"] == []


def test_cancel_active_web_prompt_marks_cancelled_when_no_worker_is_alive(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Working.",
        running_prompt="cancel this",
    )
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(module, "current_snapshot", lambda: _cheap_snapshot(module))

    snapshot = module.cancel_active_web_prompt(clear_queue=False)

    assert snapshot["pending"] is False
    meta = module.load_status_meta()
    assert meta["state"] == "cancelled"
    assert meta["pending"] is False
    assert (
        module.read_text(module.LAST_RESPONSE_PATH)
        == module.CANCELLED_WEB_REPLY_MESSAGE
    )
    assert (
        module.read_text(module.LAST_ERROR_PATH) == module.CANCELLED_WEB_REPLY_MESSAGE
    )


def test_relay_callback_notification_posts_completion(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)

    posted = module.notify_relay_callback(
        {
            "relay_id": "relay-test-0001",
            "callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
            "source_channel_id": 1,
            "source_message_id": 42,
        },
        success=True,
        summary="Target completed the work.",
        thread_id="thread-123",
        started_at=100,
        finished_at=200,
    )

    assert posted is True
    assert len(requests) == 1
    request, timeout = requests[0]
    assert timeout == 8
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["relay_id"] == "relay-test-0001"
    assert payload["source_message_id"] == 42
    assert payload["status"] == "closed"
    assert payload["success"] is True
    assert payload["target"] == module.AGENT_NAME


def test_bbs_relay_prompt_starts_when_console_is_idle(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    requests = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    def fake_execute(prompt, speed, detail, attachments):
        return "Relay work completed.", "", "thread-relay", module.default_usage_entry()

    monkeypatch.setattr(module.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module, "_execute_codex_prompt", fake_execute)

    accepted, snapshot = module.start_web_prompt(
        "Close the BBS loop.",
        "careful",
        5,
        [],
        relay_callback={
            "relay_id": "relay-idle",
            "callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
            "source_channel_id": 1,
            "source_message_id": 42,
            "target_connector_name": "queue-target",
        },
    )

    assert accepted is True
    assert snapshot["pending"] is True
    worker = module.ACTIVE_PROMPT_THREAD
    assert worker is not None
    worker.join(timeout=2)
    assert not worker.is_alive()

    final_snapshot = module.current_snapshot()
    assert final_snapshot["pending"] is False
    assert final_snapshot["queue_depth"] == 0
    assert len(requests) == 1
    payload = json.loads(requests[0][0].data.decode("utf-8"))
    assert payload["relay_id"] == "relay-idle"
    assert payload["status"] == "closed"
    assert payload["success"] is True
    assert payload["thread_id"] == "thread-relay"


def test_bbs_relay_prompt_queues_when_console_is_busy(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.ensure_state_dir()
    module.update_status_meta(
        pending=True,
        state="running",
        status_message="Already working.",
        running_prompt="Existing operator prompt.",
        running_speed="balanced",
        running_detail=3,
    )
    module.ACTIVE_PROMPT_THREAD = SimpleNamespace(is_alive=lambda: True)

    accepted, snapshot = module.start_web_prompt(
        "Close this BBS loop after the current turn.",
        "careful",
        5,
        [],
        relay_callback={
            "relay_id": "relay-busy",
            "callback_url": "http://source.local/api/v1/channels/1/relay-callback?relay_token=abc",
            "source_channel_id": 1,
            "source_message_id": 43,
            "target_connector_name": "queue-target",
        },
    )

    assert accepted is True
    assert snapshot["pending"] is True
    queued = module.normalize_queue(snapshot["queued_prompts"])
    assert len(queued) == 1
    assert queued[0]["prompt"] == "Close this BBS loop after the current turn."
    assert queued[0]["speed"] == "careful"
    assert queued[0]["detail"] == 5
    assert queued[0]["relay_callback"]["relay_id"] == "relay-busy"
    assert queued[0]["relay_callback"]["target_connector_name"] == "queue-target"
    assert module.load_status_meta()["running_prompt"] == "Existing operator prompt."

    module.ACTIVE_PROMPT_THREAD = None


def test_console_links_load_from_state_file(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    module.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (module.STATE_DIR / "console_links.json").write_text(
        json.dumps(
            {
                "links": [
                    {
                        "label": "Phone Ops",
                        "group": "Personal",
                        "url": "https://phone.home.arpa/?token=phone-token",
                        "lan_url": "http://192.168.0.146:8790/?token=phone-token",
                        "featured": True,
                        "priority": 170,
                    }
                ],
                "source": "test",
            }
        ),
        encoding="utf-8",
    )

    links = module.load_console_links_file()

    assert links == [
        {
            "label": "Phone Ops",
            "group": "Personal",
            "url": "https://phone.home.arpa/?token=phone-token",
            "lan_url": "http://192.168.0.146:8790/?token=phone-token",
            "featured": True,
            "priority": 170,
        }
    ]


def test_runtime_model_selection_persists(monkeypatch, tmp_path) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)

    saved = module.save_runtime_settings({"model": "gpt-5.5"})

    assert saved["model"] == "gpt-5.5"
    assert module.load_runtime_settings()["model"] == "gpt-5.5"
    assert module.configured_chat_model() == "gpt-5.5"
    assert module.chat_model_update_available() is False


def test_console_source_mentions_manual_model_controls() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'data-chat-model="' in source
    assert '"/api/model"' in source
    assert "Model update available" in source


def test_launch_script_reads_runtime_model_override() -> None:
    source = LAUNCH_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "HOUSEBOT_CODEX_MODEL:-gpt-5.5" in source
    assert "runtime_settings.json" in source
    assert 'MODEL="$RUNTIME_MODEL"' in source


def test_console_source_uses_scrollable_mobile_settings_sheet() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'id="settings-body"' in source
    assert ".settings-body" in source
    assert "max-height: min(calc(100dvh - 92px), 760px);" in source


def test_console_source_anchors_topbar_menu_from_viewport() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "function syncTopbarMenuPosition()" in source
    assert "top: var(--topbar-menu-top, 54px);" in source
    assert "right: var(--topbar-menu-right, 12px);" in source
    assert source.index("</header>") < source.index(
        '<div id="topbar-menu" class="topbar-menu surface"'
    )


def test_console_source_keeps_host_mentions_non_addressable() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"hal": {' in source
    assert (
        '"aliases": ("hal", "hal.home.arpa", "hal.tail00000.ts.net", "192.168.0.137")'
        in source
    )
    assert 'const baseKind = String(base.kind || "mention");' in source
    assert 'const mentionable = baseKind !== "host";' in source
    assert "function renderNameCartouche(label, options = {{}}) {{" in source
    assert "function renderLinkedNameCartouche(label, options = {{}}) {{" in source
    assert ".entity-cartouche__label {" in source
    assert "--cartouche-rail" in source
    assert '<span class="entity-cartouche__label">' in source
    assert "function tuiHrefForLabel(label) {{" in source
    assert (
        "renderEntityCartouche({{ ...base, mark, tone }}, "
        "`@${{label}}`, {{ mention: mentionable }})" in source
    )


def test_console_source_promotes_all_host_addresses_to_cartouches() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"hal.home.arpa"' in source
    assert '"toy-box.tail00000.ts.net"' in source
    assert '"private.home.example.test"' in source
    assert '"192.168.0.241"' in source
    assert "function indexInlineEntityMap(entries) {{" in source
    assert (
        "[entity.key, entity.label, entry.alias].map(normalizeInlineEntityKey)"
        in source
    )
    assert "home\\.lollie\\.org" in source
    assert "tail[0-9]+\\.ts\\.net" in source
    assert "function renderSwitcherHostCartouche(host) {{" in source
    assert "renderSwitcherHostCartouche(item.host)" in source


def test_console_source_labels_glimpser_bot_lane_as_eyebat() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"glimpser": {\n        "label": "Eyebat",' in source
    assert '"Glimpser",' in source
    assert '"glimpser",' in source


def test_runtime_stale_rollout_thread_error_is_suppressed() -> None:
    source = WEB_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "CODEX_ROLLOUT_THREAD_NOT_FOUND_RE" in source
    assert "codex_rollout_thread_not_found_ids(proc.stderr)" in source
    assert "Codex resume state was stale and has been reset." in source


def test_load_history_suppresses_stale_rollout_thread_error(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    stale_thread_id = "019d21b8-7ac3-7522-9346-1accb2ab9b04"
    error_line = (
        "2026-04-29T15:00:39.680162Z ERROR codex_core::session: "
        f"failed to record rollout items: thread {stale_thread_id} not found"
    )

    module.HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    module.HISTORY_PATH.write_text(
        json.dumps({"error": error_line, "response": "Still returned a response."})
        + "\n",
        encoding="utf-8",
    )

    history = module.load_history()

    assert history[0]["error"] == ""


def test_execute_prompt_resets_stale_resume_thread_and_hides_noise(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    stale_thread_id = "019d21b8-7ac3-7522-9346-1accb2ab9b04"
    error_line = (
        "2026-04-29T15:00:39.680162Z ERROR codex_core::session: "
        f"failed to record rollout items: thread {stale_thread_id} not found"
    )
    module.write_text(module.THREAD_ID_PATH, stale_thread_id)

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdout, stderr, env, start_new_session):
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.write_text("Recovered response.", encoding="utf-8")

        def communicate(self):
            return "", error_line

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, _usage = module._execute_codex_prompt(
        "status?", "balanced", 3, []
    )

    assert response == "Recovered response."
    assert error_text == ""
    assert thread_id == ""
    assert module.read_text(module.THREAD_ID_PATH) == ""


def test_execute_prompt_suppresses_stale_rollout_turn_failed_event(
    monkeypatch, tmp_path
) -> None:
    module = _load_norman_codex_web(monkeypatch, tmp_path)
    stale_thread_id = "019dbfd3-16a3-7cf0-8050-d30887e95c3d"
    error_line = (
        "2026-05-02T13:05:37.384478Z ERROR codex_core::session: "
        f"failed to record rollout items: thread {stale_thread_id} not found"
    )
    module.write_text(module.THREAD_ID_PATH, stale_thread_id)

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdout, stderr, env, start_new_session):
            output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
            output_path.write_text("Recovered from JSON error path.", encoding="utf-8")

        def communicate(self):
            stdout = json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": error_line},
                }
            )
            return stdout, ""

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)

    response, error_text, thread_id, _usage = module._execute_codex_prompt(
        "test", "balanced", 3, []
    )

    assert response == "Recovered from JSON error path."
    assert error_text == ""
    assert thread_id == ""
    assert module.read_text(module.THREAD_ID_PATH) == ""
