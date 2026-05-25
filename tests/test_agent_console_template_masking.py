from __future__ import annotations

import io
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _load_agent_console_web():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_web.py"
    )
    spec = importlib.util.spec_from_file_location("agent_console_web", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _agent_console_web_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_web.py"
    ).read_text(encoding="utf-8")


def _agent_console_launch_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_launch.sh"
    ).read_text(encoding="utf-8")


def _agent_prompt_template_source(name: str) -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "prompts"
        / name
    ).read_text(encoding="utf-8")


def _agent_console_supervisor_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_supervisor.sh"
    ).read_text(encoding="utf-8")


def _load_sync_agent_console_template():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "sync_agent_console_template.py"
    )
    spec = importlib.util.spec_from_file_location(
        "sync_agent_console_template", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sync_agent_console_template_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "sync_agent_console_template.py"
    ).read_text(encoding="utf-8")


def _systemd_unit_source(name: str) -> str:
    return (
        Path(__file__).resolve().parents[1] / "scripts" / "systemd" / name
    ).read_text(encoding="utf-8")


def _make_handler(module):
    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()

    class _Headers(dict):
        def get(self, key: str, default: str = "") -> str:
            return str(super().get(key, default))

    handler.headers = _Headers({"Host": "keystone.home.arpa"})
    handler.client_address = ("127.0.0.1", 443)
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.auth_cookie_token = lambda: ""
    handler.maybe_send_auth_cookie = lambda params: None
    return handler


def _bot_proxy_renderer_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "render_norman_bot_proxy_caddy.py"
    ).read_text(encoding="utf-8")


def _load_bot_proxy_renderer():
    _load_sync_agent_console_template()
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "render_norman_bot_proxy_caddy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "render_norman_bot_proxy_caddy", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _home_js_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "home.js"
    ).read_text(encoding="utf-8")


def _styles_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "styles.css"
    ).read_text(encoding="utf-8")


def _messages_log_template_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "messages_log.html"
    ).read_text(encoding="utf-8")


def _base_template_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "base.html"
    ).read_text(encoding="utf-8")


def _index_template_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "index.html"
    ).read_text(encoding="utf-8")


def _systems_js_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "systems.js"
    ).read_text(encoding="utf-8")


def test_mask_sensitive_multiline_html_masks_assignment_values() -> None:
    module = _load_agent_console_web()

    rendered = module._mask_sensitive_multiline_html(
        "username=operator\npassword: hunter2\nclient_secret='abc123'"
    )

    assert "hunter2" in rendered
    assert "abc123" in rendered
    assert rendered.count('class="secret-spoiler"') == 2
    assert "password: " in rendered
    assert "client_secret=" in rendered


def test_mask_sensitive_pre_html_masks_query_tokens_and_bearer_values() -> None:
    module = _load_agent_console_web()

    rendered = module._mask_sensitive_pre_html(
        "https://example.com/callback?token=secret-token\nAuthorization: Bearer jwt-value"
    )

    assert rendered.count('class="secret-spoiler"') == 2
    assert rendered.count('class="secret-spoiler-value"') == 2
    assert "?token=" in rendered
    assert "Bearer " in rendered


def test_render_token_gate_uses_password_input_and_reveal_toggle() -> None:
    module = _load_agent_console_web()
    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None

    module.Handler.render_token_gate(handler, {"token": ["open-sesame"]})
    rendered = handler.wfile.getvalue().decode("utf-8")

    assert 'type="password"' in rendered
    assert 'id="reveal-token"' in rendered
    assert "Show" in rendered


def test_prompt_input_registers_enter_fallback_for_line_break_clients() -> None:
    source = _agent_console_web_source()

    assert 'el.promptInput.addEventListener("keydown"' in source
    assert 'el.promptInput.addEventListener("beforeinput"' in source
    assert "function shouldSubmitPromptOnBeforeInput(event)" in source
    assert "function submitPromptFromKeyboard(event)" in source
    assert "keyCode === 13" in source


def test_prompt_and_tmux_inputs_support_console_style_ctrl_u_line_kill() -> None:
    source = _agent_console_web_source()

    assert "function isConsoleLineKillShortcut(event)" in source
    assert 'String(event.key || "").toLowerCase() === "u"' in source
    assert "function clearTextareaLikeConsole(textarea)" in source
    assert 'textarea.dispatchEvent(new Event("input", {{ bubbles: true }}));' in source
    assert "function maybeKillInputLine(event)" in source
    assert "active === el.promptInput || target === el.promptInput" in source
    assert "active === el.tmuxInput || target === el.tmuxInput" in source
    assert "if (maybeKillInputLine(event)) {{" in source
    assert 'el.tmuxInput.addEventListener("keydown", (event) => {{' in source


def test_template_exposes_explicit_web_cancel_and_queue_controls() -> None:
    source = _agent_console_web_source()

    assert "Cancel Current Web Reply" in source
    assert "Cancel + Clear Queue" in source
    assert "Clear Queue" in source
    assert "Promote Latest" in source
    assert "Interrupt tmux Session" in source
    assert '"/api/cancel-web"' in source
    assert '"/api/cancel-all"' in source
    assert '"/api/queue/clear"' in source
    assert '"/api/queue/promote-latest"' in source
    assert "Working on:" in source
    assert "New messages will be queued" in source
    assert "BBS / passive" in source
    assert "Queued ·" in source
    assert (
        "Recovered queued work after restart. Review the queue before resuming."
        in source
    )


def test_template_tracks_active_codex_exec_process_for_web_cancel() -> None:
    source = _agent_console_web_source()

    assert "ACTIVE_CODEX_PROC" in source
    assert "ACTIVE_CODEX_LOCK" in source
    assert "CANCELLED_WEB_REPLY_MESSAGE" in source
    assert "start_new_session=True" in source
    assert "def terminate_process_group" in source
    assert "active_child_pid" in source
    assert "active_child_pgid" in source
    assert "cancel_requested_at" in source
    assert "os.killpg(target_pgid, signal.SIGTERM)" in source
    assert "os.killpg(target_pgid, signal.SIGKILL)" in source


def test_template_exposes_browser_console_shortcuts() -> None:
    source = _agent_console_web_source()

    assert "function shortcutEligibleTarget(event) {" in source
    assert "function openShortcutGuide() {" in source
    assert (
        "function editableShortcutTarget(target = document.activeElement) {" in source
    )
    assert "function jumpToLatestConversation() {" in source
    assert "function handleGlobalConsoleShortcut(event) {" in source
    assert 'key === "/"' in source
    assert 'key === "?" || (key === "/" && event.shiftKey)' in source
    assert 'lowerKey === "k"' in source
    assert 'key === "End"' in source
    assert "setSwitcherOpen(true);" in source
    assert "openShortcutGuide();" in source
    assert "focusPromptInputAtEnd();" in source
    assert "jumpToLatestConversation();" in source
    assert "<kbd>/</kbd><span>Prompt</span>" in source
    assert "<kbd>Mod+K</kbd><span>Switch</span>" in source
    assert "<kbd>End</kbd><span>Latest</span>" in source
    assert "<kbd>Esc</kbd><span>Close</span>" in source
    assert "<kbd>?</kbd><span>Help</span>" in source
    assert ".topbar-menu-shortcuts {" in source
    assert ".shortcut-chip kbd {" in source
    assert 'title="Switch agents (Ctrl/Cmd+K)"' in source
    assert 'title="Jump to latest (End)"' in source
    assert "if (handleGlobalConsoleShortcut(event)) {{" in source
    assert "function maybeFocusPromptFromEscape(event) {" in source
    assert "if (maybeInterruptFromEscape(event)) {{" in source
    assert "maybeFocusPromptFromEscape(event);" in source


def test_supervisor_always_clears_visible_update_interstitials() -> None:
    source = _agent_console_supervisor_source()

    assert '[[ "$AUTO_CLEAR_UPDATE_INTERSTITIAL" == "0" ]] && return 1' in source
    assert (
        'if [[ "$pane_text" == *"Update available!"* && "$pane_text" == *"Press enter to continue"* ]]; then'
        in source
    )
    assert 'tmux_cmd send-keys -t "${SESSION}:0.0" Down Enter' in source
    assert "UPDATE_MARKER" not in source


def test_template_compacts_top_chrome_in_working_mode() -> None:
    source = _agent_console_web_source()

    assert "body.chat-scrolled .brand {" in source
    assert "body.chat-scrolled .prime-home-button," in source
    assert "body.chat-scrolled .directory-home-button {{" in source
    assert "body.chat-scrolled .chat-summary-bar {" in source
    assert "body.chat-scrolled .meta-chip {" in source
    assert "body.chat-scrolled #context-meter-value," in source
    assert "body.chat-scrolled .kpi-strip {" in source
    assert "body.chat-scrolled .kpi-capsule {" in source


def test_mobile_composer_tracks_visual_viewport_and_keyboard_state() -> None:
    source = _agent_console_web_source()

    assert "--viewport-height: 100dvh;" in source
    assert "--keyboard-inset: 0px;" in source
    assert "body.mobile-keyboard-open" in source


def test_template_exposes_structured_audit_feed_for_central_collection() -> None:
    source = _agent_console_web_source()

    assert 'AUDIT_PATH = STATE_DIR / "audit.jsonl"' in source
    assert "def append_audit_event(" in source
    assert 'if parsed.path == "/api/audit":' in source
    assert '"session_name": SESSION' in source
    assert '"agent_name": AGENT_NAME' in source
    assert '"host_name": HOST_NAME' in source
    assert "body.mobile-compose-mode" in source
    assert "function keyboardLikelyOpen()" in source
    assert "function syncMobileComposeMode()" in source
    assert "function applyViewportMetrics(options = {{}})" in source
    assert '"--viewport-height"' in source
    assert '"--keyboard-inset"' in source
    assert (
        'document.body.classList.toggle("mobile-keyboard-open", nextKeyboardOpen);'
        in source
    )
    assert 'document.body.classList.toggle("mobile-compose-mode", composing);' in source
    assert "#prime-home-button," in source
    assert "#directory-home-button {" in source
    assert ".switcher-toggle-label," in source
    assert "body.mobile-compose-mode .context-save-button {" in source
    assert 'if (document.body.classList.contains("switcher-open")) {{' in source
    assert "setSwitcherOpen(false);" in source
    assert 'window.addEventListener("orientationchange", () => {{' in source
    assert "nextKeyboardOpen && wasNearBottom && scroller" in source


def test_chat_file_links_surface_inline_previews_without_clickthrough() -> None:
    source = _agent_console_web_source()

    assert "function extractPreviewableFileTargets(value, limit = 2)" in source
    assert r"text.matchAll(/\[([^\]]+)\]\s*\(\s*(<[^>\\n]+>|[^\s)]+)\s*\)/g)" in source
    assert "function loadInlineFilePreview(entry)" in source
    assert (
        'const normalized = raw.replace(/\\\\r\\\\n/g, "\\\\n").replace(/\\\\r/g, "\\\\n");'
        in source
    )
    assert 'const lines = normalized.split("\\\\n");' in source
    assert "function renderInlineFilePreviews(container, targets)" in source
    assert ".message-file-previews {" in source
    assert ".inline-file-preview-body img {" in source
    assert 'pre.className = "inline-file-preview-text";' in source
    assert 'previews.className = "message-file-previews";' in source
    assert "renderInlineFilePreviews(previews, previewTargets);" in source


def test_prompt_input_registers_clipboard_image_fallbacks() -> None:
    source = _agent_console_web_source()

    assert "function clipboardFilesFromEvent(event)" in source
    assert "clipboard.files || []" in source
    assert "if (files.length) {{" in source
    assert "return dedupeFiles(files);" in source
    assert 'item.kind !== "file"' in source
    assert "async function readClipboardImageFiles()" in source
    assert "navigator.clipboard.read" in source
    assert "async function readClipboardPlainText()" in source
    assert "navigator.clipboard.readText" in source
    assert "Clipboard image" in source


def test_prompt_input_marks_paste_events_to_avoid_duplicate_clipboard_uploads() -> None:
    source = _agent_console_web_source()

    assert "event.__normanPromptPasteRouted" in source
    assert "if (event.target === el.promptInput)" in source


def test_sync_codex_home_seed_does_not_share_auth_files_between_bots() -> None:
    source = _sync_agent_console_template_source()

    assert 'config_source = source_home / "config.toml"' in source
    assert 'models_source = source_home / "models_cache.json"' in source
    assert 'auth_source = source_home / "auth.json"' not in source
    assert "auth_target.symlink_to" not in source


def test_sync_template_trusts_pixel_phone_for_tokenless_console_and_auth_bridge() -> (
    None
):
    source = _sync_agent_console_template_source()

    assert '"192.168.0.136",  # pixel10' in source
    assert source.count('"192.168.0.136",  # pixel10') >= 2


def test_prompt_input_rerouted_plain_text_paste_inserts_into_composer() -> None:
    source = _agent_console_web_source()

    assert "function insertTextIntoPrompt(text, options = {{}})" in source
    assert (
        "const reroutedPaste = Boolean(event && event.target && event.target !== el.promptInput);"
        in source
    )
    assert "insertTextIntoPrompt(pastedText, {{ placeAtEnd: true }});" in source


def test_composer_reserve_preserves_live_edge_without_forcing_scroll_snap() -> None:
    source = _agent_console_web_source()

    assert "pendingComposerReserveLiveEdge" in source
    assert "lastComposerReserve" in source
    assert "function applyComposerReserve(options = {{}})" in source
    assert "scheduleComposerReserve({{ preserveLiveEdge: true }})" in source
    assert "scroller.scrollTop = Math.max(0, scroller.scrollTop + delta);" in source


def test_render_conversation_preserves_pinned_viewport_when_new_reply_lands() -> None:
    source = _agent_console_web_source()

    assert "function conversationTailKey(snapshot = state.snapshot)" in source
    assert "function restoreConversationViewport(scrollTop, showJump = false)" in source
    assert (
        "const shouldPreserveViewport = !state.historyExpanded && !shouldStick;"
        in source
    )
    assert "restoreConversationViewport(previousScrollTop, tailChanged);" in source
    assert 'el.jumpLatestButton.classList.toggle("visible",' in source


def test_template_exposes_brokered_handoff_affordances() -> None:
    source = _agent_console_web_source()

    assert "function brokerInsight(snapshot = state.snapshot)" in source
    assert 'stripTitle: "Broker through Norman"' in source
    assert 'label: "Broker"' in source
    assert '"Ask another"' in source
    assert "openLatestRelayTargets()" in source


def test_template_exposes_switchboard_and_activity_track() -> None:
    source = _agent_console_web_source()

    assert "Switchboard" in source
    assert 'id="console-switcher-seed"' in source
    assert 'id="activity-track"' in source
    assert "function compactActivityStepLabel(label)" in source


def test_activity_strip_copy_and_canvas_focus_hooks_are_present() -> None:
    source = _agent_console_web_source()

    assert 'line: "Sending to worker"' in source
    assert 'label: "Accepted"' in source
    assert 'label: "Return reply"' in source
    assert "function activityStepProgress(steps)" in source
    assert "function activityTrackSummary(steps)" in source
    assert (
        "grid-template-columns: auto minmax(0, 1fr) minmax(124px, 22vw) auto;" in source
    )
    assert 'startedParts.find((item) => item.includes("in flight")) || ""' in source
    assert 'queueDepth > 0 ? `+${{queueDepth}} queued` : ""' in source
    assert 'class="activity-track-bar"' in source
    assert 'class="activity-track-summary"' in source
    assert "scheduleComposerReserve({{ preserveLiveEdge: true }});" in source
    assert "function shouldFocusPromptFromCanvasClick(event)" in source
    assert 'el.workspace.addEventListener("click", (event) => {' in source


def test_browser_signin_uses_local_bridge_launch_redirect() -> None:
    source = _agent_console_web_source()

    assert "function browserAuthBridgeLaunchHref(authUrl)" in source
    assert 'const launch = new URL("/arm", browserAuthBridgeApiBase());' in source
    assert (
        'launch.searchParams.set("forward_url", browserAuthHelperAbsoluteHref());'
        in source
    )
    assert (
        'launch.searchParams.set("next_url", String(authUrl || "").trim());' in source
    )
    assert "popup.location.replace(launchHref);" in source


def test_browser_signin_callback_runs_post_auth_self_check() -> None:
    source = _agent_console_web_source()

    assert (
        "def _run_post_auth_self_check(*, timeout: float = 10.0) -> tuple[bool, str]:"
        in source
    )
    assert 'detail = f"{AGENT_NAME} is ready. Self-check passed."' in source
    assert (
        "self_check_ok, self_check_detail = _run_post_auth_self_check(timeout=10.0)"
        in source
    )
    assert 'last_action="auth-browser-self-check"' in source


def test_auth_state_ignores_stale_refresh_token_errors_once_codex_is_ready() -> None:
    module = _load_agent_console_web()

    auth = module._auth_state_from_console(
        "OpenAI Codex (v0.118.0)\nmodel: gpt-5.4 xhigh\ndirectory: ~/code/autocamera",
        'ERROR refresh_token_reused: "already been used to generate a new access token"',
    )

    assert auth["required"] is False
    assert auth["mode"] == ""


def test_current_snapshot_clears_stale_auth_error_when_session_is_ready() -> None:
    module = _load_agent_console_web()

    with tempfile.TemporaryDirectory() as temp_dir:
        last_error_path = Path(temp_dir) / "last_error.txt"
        last_error_path.write_text(
            'ERROR refresh_token_reused: "already been used to generate a new access token"',
            encoding="utf-8",
        )
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        module.load_status_meta = lambda: module.default_status_meta()
        module.load_history = lambda: []
        module.read_text = (
            lambda path, default="": last_error_path.read_text(encoding="utf-8")
            if Path(path) == last_error_path
            else default
        )
        module.write_text = (
            lambda path, value: last_error_path.write_text(value, encoding="utf-8")
            if Path(path) == last_error_path
            else None
        )
        module.capture_pane = (
            lambda: "OpenAI Codex (v0.118.0)\nmodel: gpt-5.4 xhigh\ndirectory: ~/code/autocamera"
        )
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False

        snapshot = module.current_snapshot()

        assert snapshot["auth"]["required"] is False
        assert snapshot["last_error"] == ""
        assert last_error_path.read_text(encoding="utf-8") == ""


def test_current_snapshot_treats_modern_inline_codex_prompt_as_ready() -> None:
    module = _load_agent_console_web()

    with tempfile.TemporaryDirectory() as temp_dir:
        last_error_path = Path(temp_dir) / "last_error.txt"
        last_error_path.write_text("", encoding="utf-8")
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        module.load_status_meta = lambda: {
            **module.default_status_meta(),
            "state": "error",
            "status_message": "Web prompt failed.",
        }
        module.load_history = lambda: []
        module.read_text = (
            lambda path, default="": last_error_path.read_text(encoding="utf-8")
            if Path(path) == last_error_path
            else default
        )
        module.write_text = (
            lambda path, value: last_error_path.write_text(value, encoding="utf-8")
            if Path(path) == last_error_path
            else None
        )
        module.capture_pane = (
            lambda: "› Summarize recent commits\n\n  gpt-5.4 xhigh fast · 84% left · ~/code/d.ace"
        )
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False

        snapshot = module.current_snapshot()

        assert snapshot["auth"]["required"] is False
        assert snapshot["state"] == "ok"
        assert snapshot["status_message"] == "Ready."


def test_current_snapshot_clears_stale_auth_error_when_snapshot_state_is_ok() -> None:
    module = _load_agent_console_web()

    with tempfile.TemporaryDirectory() as temp_dir:
        last_error_path = Path(temp_dir) / "last_error.txt"
        last_error_path.write_text(
            'ERROR refresh_token_reused: "already been used to generate a new access token"',
            encoding="utf-8",
        )
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        module.load_status_meta = lambda: {
            **module.default_status_meta(),
            "state": "ok",
            "status_message": "Web prompt completed.",
        }
        module.load_history = lambda: []
        module.read_text = (
            lambda path, default="": last_error_path.read_text(encoding="utf-8")
            if Path(path) == last_error_path
            else default
        )
        module.write_text = (
            lambda path, value: last_error_path.write_text(value, encoding="utf-8")
            if Path(path) == last_error_path
            else None
        )
        module.capture_pane = lambda: "acknowledged\n"
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False

        snapshot = module.current_snapshot()

        assert snapshot["state"] == "ok"
        assert snapshot["auth"]["required"] is False
        assert snapshot["last_error"] == ""
        assert last_error_path.read_text(encoding="utf-8") == ""


def test_initial_conversation_hides_stale_token_reuse_history_error_when_ready() -> (
    None
):
    module = _load_agent_console_web()

    snapshot = {
        "history": [
            {
                "prompt": "status?",
                "response": "[no response returned]",
                "error": 'ERROR refresh_token_reused: "already been used to generate a new access token"',
                "started_at": 0,
                "finished_at": 0,
                "speed": "balanced",
                "detail": 3,
            }
        ],
        "pending": False,
        "pane": "OpenAI Codex (v0.118.0)\nmodel: gpt-5.4 xhigh\ndirectory: ~/code/autocamera",
        "auth": {"required": False, "mode": "", "summary": ""},
    }

    rendered = module._initial_conversation_html(snapshot)

    assert "refresh_token_reused" not in rendered
    assert "already been used to generate a new access token" not in rendered
    assert "[no response returned]" in rendered


def test_history_error_is_stale_when_runtime_is_at_update_interstitial() -> None:
    module = _load_agent_console_web()

    pane = (
        "✨\u200aUpdate available! 0.116.0 -> 0.118.0\n\n"
        "  Release notes: https://github.com/openai/codex/releases/latest\n\n"
        "› 1. Update now (runs `npm install -g @openai/codex`)\n"
        "  2. Skip\n"
        "  3. Skip this version\n\n"
        "Press enter to continue\n"
    )

    assert (
        module._history_error_is_stale(
            'ERROR refresh_token_reused: "already been used to generate a new access token"',
            pane=pane,
            auth={"required": False, "mode": "", "summary": ""},
        )
        is True
    )


def test_history_error_is_stale_when_auth_is_healthy_and_last_error_is_clear() -> None:
    module = _load_agent_console_web()

    assert (
        module._history_error_is_stale(
            'ERROR refresh_token_reused: "already been used to generate a new access token"',
            pane="acknowledged\n",
            auth={"required": False, "mode": "", "summary": ""},
            snapshot_state="running",
            last_error="",
        )
        is True
    )


def test_current_snapshot_sanitizes_stale_history_auth_errors_at_update_interstitial() -> (
    None
):
    module = _load_agent_console_web()

    pane = (
        "✨\u200aUpdate available! 0.116.0 -> 0.118.0\n\n"
        "  Release notes: https://github.com/openai/codex/releases/latest\n\n"
        "› 1. Update now (runs `npm install -g @openai/codex`)\n"
        "  2. Skip\n"
        "  3. Skip this version\n\n"
        "Press enter to continue\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        last_error_path = state_dir / "last_error.txt"
        last_error_path.write_text("", encoding="utf-8")
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        module.load_status_meta = lambda: module.default_status_meta()
        module.load_history = lambda: [
            {
                "prompt": "status?",
                "response": "[no response returned]",
                "error": 'ERROR refresh_token_reused: "already been used to generate a new access token"',
                "started_at": 0,
                "finished_at": 0,
                "speed": "balanced",
                "detail": 3,
                "attachments": [],
                "usage": {},
            }
        ]
        module.read_text = (
            lambda path, default="": last_error_path.read_text(encoding="utf-8")
            if Path(path) == last_error_path
            else default
        )
        module.write_text = (
            lambda path, value: last_error_path.write_text(value, encoding="utf-8")
            if Path(path) == last_error_path
            else None
        )
        module.capture_pane = lambda: pane
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False

        snapshot = module.current_snapshot()

        assert snapshot["auth"]["required"] is False
        assert len(snapshot["history"]) == 1
        assert snapshot["history"][0]["error"] == ""


def test_current_snapshot_sanitizes_stale_history_auth_errors_when_lane_is_ok() -> None:
    module = _load_agent_console_web()

    pane = (
        "OpenAI Codex (v0.118.0)\n"
        "model: gpt-5.4 xhigh\n"
        "directory: ~/code/platinum_standard\n"
        "› Write tests for @filename\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        last_error_path = state_dir / "last_error.txt"
        last_error_path.write_text("", encoding="utf-8")
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        meta = module.default_status_meta()
        meta["state"] = "ok"
        meta["status_message"] = "Web prompt completed."
        module.load_status_meta = lambda: meta
        module.load_history = lambda: [
            {
                "prompt": "status?",
                "response": "[no response returned]",
                "error": 'ERROR refresh_token_reused: "already been used to generate a new access token"',
                "started_at": 0,
                "finished_at": 0,
                "speed": "balanced",
                "detail": 3,
                "attachments": [],
                "usage": {},
            }
        ]
        module.read_text = (
            lambda path, default="": last_error_path.read_text(encoding="utf-8")
            if Path(path) == last_error_path
            else default
        )
        module.write_text = (
            lambda path, value: last_error_path.write_text(value, encoding="utf-8")
            if Path(path) == last_error_path
            else None
        )
        module.capture_pane = lambda: pane
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False

        snapshot = module.current_snapshot()

        assert snapshot["state"] == "ok"
        assert snapshot["auth"]["required"] is False
        assert len(snapshot["history"]) == 1
        assert snapshot["history"][0]["error"] == ""


def test_current_snapshot_requires_reauth_when_latest_web_turn_failed_with_zero_tokens() -> (
    None
):
    module = _load_agent_console_web()

    pane = (
        "› Explain the workbook\n\n"
        "  gpt-5.4 xhigh fast · 87% left · ~/code/control_plane"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        last_error_path = state_dir / "last_error.txt"
        last_error_path.write_text("", encoding="utf-8")
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        meta = module.default_status_meta()
        meta["state"] = "ok"
        meta["status_message"] = "Ready."
        module.load_status_meta = lambda: meta
        module.load_history = lambda: [
            {
                "prompt": "proceed",
                "response": "[no response returned]",
                "error": 'ERROR refresh_token_reused: "already been used to generate a new access token"',
                "started_at": 1712878340,
                "finished_at": 1712878366,
                "speed": "careful",
                "detail": 5,
                "attachments": [],
                "usage": {
                    "success": False,
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            }
        ]
        module.read_text = (
            lambda path, default="": last_error_path.read_text(encoding="utf-8")
            if Path(path) == last_error_path
            else default
        )
        module.write_text = (
            lambda path, value: last_error_path.write_text(value, encoding="utf-8")
            if Path(path) == last_error_path
            else None
        )
        module.capture_pane = lambda: pane
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False

        snapshot = module.current_snapshot()

        assert snapshot["state"] == "error"
        assert snapshot["status_message"] == "Needs reauth."
        assert snapshot["auth"]["required"] is True
        assert snapshot["auth"]["mode"] == "needs_reauth"
        assert "refresh_token_reused" in snapshot["last_error"]
        assert snapshot["history"][0]["error"]
        assert "refresh_token_reused" in last_error_path.read_text(encoding="utf-8")


def test_current_snapshot_preserves_device_code_prompt_over_latest_reauth_history() -> (
    None
):
    module = _load_agent_console_web()

    pane = (
        "Complete device-code sign-in in your browser\n\n"
        "https://auth.openai.com/codex/device\n\n"
        "Enter this one-time code: 9W70-PG42M\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        last_error_path = state_dir / "last_error.txt"
        last_error_path.write_text("", encoding="utf-8")
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        meta = module.default_status_meta()
        meta["state"] = "error"
        meta["status_message"] = "Needs reauth."
        module.load_status_meta = lambda: meta
        module.load_history = lambda: [
            {
                "prompt": "proceed",
                "response": "[no response returned]",
                "error": 'ERROR refresh_token_reused: "already been used to generate a new access token"',
                "started_at": 1712878340,
                "finished_at": 1712878366,
                "speed": "careful",
                "detail": 5,
                "attachments": [],
                "usage": {
                    "success": False,
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            }
        ]
        module.read_text = (
            lambda path, default="": last_error_path.read_text(encoding="utf-8")
            if Path(path) == last_error_path
            else default
        )
        module.write_text = (
            lambda path, value: last_error_path.write_text(value, encoding="utf-8")
            if Path(path) == last_error_path
            else None
        )
        module.capture_pane = lambda: pane
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False

        snapshot = module.current_snapshot()

        assert snapshot["auth"]["required"] is True
        assert snapshot["auth"]["mode"] == "device_code"
        assert snapshot["auth"]["device_code"] == "9W70-PG42M"


def test_update_interstitial_detection_ignores_stale_scrollback() -> None:
    module = _load_agent_console_web()

    stale_pane = (
        "Update available! 0.116.0 -> 0.118.0\n"
        "Press enter to continue\n"
        "OpenAI Codex (v0.118.0)\n"
        "directory: ~/code/autocamera\n"
    )

    assert module._contains_update_interstitial(stale_pane) is True
    assert module._update_interstitial_is_stale(stale_pane) is True
    assert module._contains_active_update_interstitial(stale_pane) is False


def test_template_ignores_stale_update_interstitials_when_runtime_is_ready() -> None:
    source = _agent_console_web_source()

    assert "def _update_interstitial_is_stale(text: str) -> bool:" in source
    assert "def _contains_active_update_interstitial(text: str) -> bool:" in source
    assert "def _contains_codex_ready_prompt(text: str) -> bool:" in source
    assert '"% left ·"' in source
    assert "if _contains_active_update_interstitial(latest):" in source
    assert "if _contains_active_update_interstitial(pane):" in source
    assert "function containsCodexReadyPrompt(value) {{" in source
    assert "function updateInterstitialIsStale(value) {{" in source
    assert "function containsActiveUpdateInterstitial(value) {{" in source
    assert "if (containsActiveUpdateInterstitial(pane)) {{" in source


def test_template_hides_stale_history_auth_errors_when_runtime_is_ready() -> None:
    source = _agent_console_web_source()

    assert "def _history_entry_requires_reauth(entry: Any) -> bool:" in source
    assert "def _latest_history_requires_reauth(" in source
    assert "def _history_error_is_stale(" in source
    assert "def _sanitize_history_entries(" in source
    assert "latest_history_requires_reauth: bool = False" in source
    assert "if latest_history_requires_reauth:" in source
    assert "function historyEntryRequiresReauth(entry) {{" in source
    assert "function latestHistoryRequiresReauth(snapshot) {{" in source
    assert "function staleHistoryError(snapshot, value) {{" in source
    assert "if (!staleHistoryError(snapshot, item.error)) {{" in source
    assert "|| containsActiveUpdateInterstitial(pane);" in source


def test_template_uses_window_owned_shell_frame() -> None:
    source = _agent_console_web_source()

    assert "max-width: none;" in source
    assert "width: 100%;" in source
    assert "padding: 0 10px 10px;" in source
    assert "padding: 8px 12px 7px;" in source


def test_template_makes_inline_code_urls_clickable() -> None:
    source = _agent_console_web_source()

    assert "function renderInlineCodeMarkup(value)" in source
    assert 'class="inline-code-link"' in source
    assert 'href="${{escapeHtml(url)}}"' in source
    assert "sensitive.text = sensitive.text.replace(/`([^`]+)`/g" in source


def test_template_sanitizes_raw_html_anchor_markup_before_linkifying() -> None:
    source = _agent_console_web_source()

    assert "const RAW_HTML_ANCHOR_RE =" in source
    assert "function stashRawHtmlAnchors(text)" in source
    assert (
        'const rawAnchors = stashRawHtmlAnchors(String(value || "").replace(/\\\\r\\\\n/g, "\\\\n"));'
        in source
    )
    assert "displayTextForLink(target, label)" in source


def test_template_promotes_md_like_pipe_tables_into_rich_tables() -> None:
    source = _agent_console_web_source()

    assert "function isTableSeparatorCell(cell)" in source
    assert "function isPipeTableLikeStart(lines, index)" in source
    assert (
        "rowCount >= 2 || (rowCount >= 1 && hasOuterPipe(headerLine) && hasOuterPipe(current))"
        in source
    )
    assert (
        'blocks.push(renderTableBlock(header, header.map(() => "-"), rows));' in source
    )


def test_template_polishes_reading_lane_and_composer_shell() -> None:
    source = _agent_console_web_source()

    assert "color-mix(in srgb, var(--surface) 22%, transparent) 18%" in source
    assert "border-radius: 16px;" in source
    assert (
        "border-left: 2px solid color-mix(in srgb, var(--agent-accent) 18%, transparent);"
        in source
    )
    assert "border-radius: 999px;" in source


def test_template_uses_single_motion_source_for_live_worker_state() -> None:
    source = _agent_console_web_source()

    assert ".message.pending .message-body::before" not in source
    assert 'article.classList.add("live-status");' in source
    assert ".message.pending.live-status {" in source
    assert ".message.pending.live-status .message-head {" in source
    assert "display: none;" in source
    assert ".message.pending.live-status .message-body::before {" in source
    assert ".message.pending.live-status .message-body::after {" in source
    assert "const liveStatusBody = `Working on:" in source
    assert "New messages will be queued" in source
    assert 'snapshot.model_process_alive ? "model process alive"' in source


def test_template_refines_topbar_footer_and_composer_materials() -> None:
    source = _agent_console_web_source()

    assert "--topbar-saturate: 128%;" in source
    assert "--topbar-blur: 16px;" in source
    assert (
        "backdrop-filter: saturate(var(--topbar-saturate)) blur(var(--topbar-blur));"
        in source
    )
    assert ".chat-summary-bar::before {" in source
    assert ".kpi-capsule::before {" in source
    assert ".topbar.surface::after {" in source
    assert ".message-footer::before {" in source
    assert ".message-footer > * + * {" in source
    assert ".composer-input-shell::before {" in source
    assert ".composer-input-shell::after {" in source
    assert "0 22px 48px rgba(8, 12, 18, 0.14)," in source
    assert "backdrop-filter: blur(14px) saturate(118%);" in source
    assert ".rich-table th + th," in source
    assert ".context-save-button {" in source
    assert '.context-save-button[data-save-tone="danger"] {' in source
    assert ".kpi-strip {" in source
    assert ".kpi-capsule {" in source
    assert ".system-runtime-metrics {" in source
    assert "body.mobile-compose-mode .message-tools," in source
    assert "body.mobile-compose-mode #switcher-toggle-button {" in source


def test_template_uses_agent_marks_and_orbit_tab_chrome() -> None:
    source = _agent_console_web_source()

    assert "ENTITY_MARK_ALIASES" in source
    assert "const AGENT_MARK =" in source
    assert "const TAB_TITLE_LABEL =" in source
    assert "const FAVICON_AGENT_PALETTE =" in source
    assert "function syncTabFaviconMotion(descriptor)" in source
    assert "buildStateFaviconHref(descriptor, frame = 0)" in source
    assert "identity.accent || descriptor.border" in source
    assert "identity.surface || 'rgba(255,255,255,0.035)'" in source
    assert 'descriptor.key === "ready" && queueDepth <= 0' in source


def test_launch_template_includes_norman_broker_policy() -> None:
    source = _agent_console_launch_source()

    assert "Fleet coordination policy:" in source
    assert (
        "Norman Prime / the Norman session is always an allowed coordination target"
        in source
    )
    assert (
        "Switchboard is the TUI/browser lane map, relay surface, and coordination backchannel."
        in source
    )
    assert "share this with Norman" in source
    assert '"use the Switchboard"' in source
    assert (
        "PROMPT_SHA256=\"$(printf '%s' \"$PROMPT\" | sha256sum | awk '{print $1}')\""
        in source
    )
    assert "Direct bot-to-bot communication is deny-by-default" in source
    assert "Treat Switchboard as the persistent party line" in source
    assert "Do not recommend on-demand instances as the default answer." in source
    assert "Prefer bullets, short sections, compact key-value lists" in source
    assert "Treat most TUI/web bot surfaces as the slow/default-cost path" in source
    assert "Norman Prime on norman.home.arpa is allowed to use the fast path" in source
    assert "Norman Switchboard party-line broadcast" in source
    assert "Absorb it quietly unless you are directly addressed" in source
    assert "Scout/Ranger is the work research collection lane only." in source
    assert "Use Scout for external research, Perplexity/watchlists" in source
    assert "Do not send Scout implementation, deploys, credentials" in source


def test_work_research_routing_policy_is_durable() -> None:
    docs_source = (
        Path(__file__).resolve().parents[1] / "docs" / "work_bot_system_access.md"
    ).read_text(encoding="utf-8")
    sync_source = _sync_agent_console_template_source()
    control_plane_prompt = _agent_prompt_template_source("control-plane.txt")
    scout_prompt = _agent_prompt_template_source("scout.txt")

    assert "Scout/Ranger is the work research collection lane only." in docs_source
    assert "Scout for research collection only" in docs_source
    assert "Do not send Scout:" in docs_source
    assert "route research-only collection to Scout" in sync_source
    assert "Ask Scout/Ranger for research collection only" in sync_source
    assert "Use Scout/Ranger for work research collection only" in control_plane_prompt
    assert "Control Plane is still responsible for deciding" in control_plane_prompt
    assert "You are Scout/Ranger, the work research collection lane." in scout_prompt
    assert "Do not take implementation, deploy, service restart" in scout_prompt
    assert "Return structured findings" in scout_prompt


def test_passive_party_line_history_cleanup_recognizes_all_bbs_markers() -> None:
    module = _load_agent_console_web()

    for marker in (
        "[Norman Switchboard party line]",
        "[Norman Subprime party line]",
        "[Norman BBS party line]",
    ):
        assert module._history_entry_is_passive_party_line(
            {
                "prompt": (
                    f"{marker}\n"
                    "Passive fleet context only. Absorb this silently.\n\n"
                    "fleet note"
                ),
                "response": "[no response returned]",
                "usage": {"total_tokens": 0},
            }
        )


def test_completion_bell_settings_and_reply_hook_are_present() -> None:
    source = _agent_console_web_source()

    assert 'data-setting="completionBell"' in source
    assert 'id="completion-bell-test-button"' in source
    assert "const COMPLETION_BELL_PROFILES = {{" in source
    assert (
        "const AGENT_COMPLETION_BELL_PROFILE = buildAgentCompletionBellProfile();"
        in source
    )
    assert "if (AGENT_COMPLETION_BELL_PROFILE) {{" in source
    assert 'const profile = key === "agent"' in source
    assert "function playCompletionBell(options = {{}})" in source
    assert "playCompletionBell();" in source


def test_broker_ui_mentions_switchboard_architecture() -> None:
    source = _agent_console_web_source()

    assert "Norman Prime or Switchboard should broker the next step." in source
    assert "Switchboard-brokered handoff." in source
    assert (
        "Use Norman Prime and the Switchboard to decide whether this should become a Switchboard handoff"
        in source
    )


def test_template_applies_subtle_per_agent_style_variants() -> None:
    source = _agent_console_web_source()

    assert "STYLE_VARIANTS: dict[str, dict[str, str]] = {" in source
    assert "AGENT_STYLE_VARIANT_OVERRIDES = {" in source
    assert "def style_variant_vars_css(agent_key: str) -> str:" in source
    assert "--style-variant-name:" in source
    assert "const AGENT_STYLE_VARIANT =" in source
    assert "{style_variant_vars_css(AGENT_SLUG)}" in source
    assert "linear-gradient(var(--body-accent-angle)" in source
    assert "opacity: var(--body-overlay-opacity);" in source
    assert "border-radius: var(--brand-radius);" in source
    assert "border-radius: var(--chrome-pill-radius);" in source
    assert "font-family: var(--font-reading);" in source


def test_template_uses_poppins_for_openbrand_work_surfaces() -> None:
    source = _agent_console_web_source()

    assert "def agent_font_vars_css(agent_key: str) -> str:" in source
    assert "OPENBRAND_FONT_AGENT_SLUGS = {" in source
    assert '"pefb"' in source
    assert "WORK_FONT_VARS" in source
    assert "AGENT_FONT_OVERRIDES" in source
    assert (
        'if semantic_group == "work" or agent_key in OPENBRAND_FONT_AGENT_SLUGS:'
        in source
    )
    assert "values.update(WORK_FONT_VARS)" in source
    assert "values.update(AGENT_FONT_OVERRIDES.get(agent_key, {}))" in source
    assert '"Poppins", "IBM Plex Sans"' in source
    assert "{agent_font_vars_css(AGENT_SLUG)}" in source
    assert "family=Poppins:wght@400;500;600;700" in source


def test_template_exposes_common_reply_shortcuts() -> None:
    source = _agent_console_web_source()

    assert "const REPLY_ACTIONS = {{" in source
    assert 'label: "Proceed"' in source
    assert 'label: "Dig"' in source
    assert 'label: "Unwind"' in source
    assert 'label: "Verify"' in source
    assert 'label: "Simpler"' in source
    assert 'const STABLE_REPLY_ACTION_KINDS = ["proceed", "dig", "unwind"];' in source
    assert "function scoreReplyActionKind(kind, sourcePrompt, body) {{" in source
    assert (
        "function selectDynamicReplyActionKinds(sourcePrompt, body, options = {{}}) {{"
        in source
    )
    assert (
        "function replyShortcutDescriptors(sourcePrompt, body, options = {{}}) {{"
        in source
    )
    assert (
        "function buildReplyShortcutGroup(sourcePrompt, body, options = {{}})" in source
    )
    assert "function submitPromptSuggestion(prompt) {{" in source
    assert 'group.className = String(options.className || "reply-shortcuts");' in source
    assert "actionCount: 5," in source
    assert "includeUnwind: options.canUnwindLatestTurn," in source
    assert 'className: "reply-tail-actions"' in source
    assert 'buttonClass: "ghost inline-action reply-tail-action"' in source
    assert (
        'if (descriptor.mode === "invoke" && descriptor.action === "unwind_latest_turn") {{'
        in source
    )
    assert "void unwindLatestTurn(button);" in source
    assert "if (options.submitImmediately) {{" in source
    assert "submitPromptSuggestion(descriptor.prompt);" in source
    assert "submitImmediately: true," in source
    assert 'applyPromptSuggestion(button.dataset.suggestion || "");' in source
    assert 'copyQuick.textContent = "Copy";' in source
    assert 'copyQuick.title = "Copy plain text";' in source
    assert "plainTextFromRenderedMessage(article, body)" in source
    assert 'kinds: ["make_it_so", "proceed", "simpler"]' not in source
    assert ".reply-tail-actions::-webkit-scrollbar {" in source
    assert ".reply-tail-action {" in source


def test_template_surfaces_sample_prompt_strip_in_composer() -> None:
    source = _agent_console_web_source()

    assert 'id="sample-prompt-strip"' in source
    assert 'class="sample-prompt-strip"' in source
    assert 'samplePromptStrip: document.getElementById("sample-prompt-strip")' in source
    assert "const samplePromptsHidden = (" in source
    assert "|| state.toolbarExpanded" in source
    assert "el.samplePromptStrip.hidden = samplePromptsHidden;" in source
    assert ".sample-prompt-list::-webkit-scrollbar {" in source


def test_template_exposes_relay_queue_visual_state() -> None:
    source = _agent_console_web_source()

    assert "function queueRelayCallback(item) {{" in source
    assert "function relayQueueLabel(relay) {{" in source
    assert "function relayPickupState(result, target) {{" in source
    assert "function relayEtaLabel(queuePosition, pending) {{" in source
    assert "function applyRelayButtonState(button, ack) {{" in source
    assert "function setRelayButtonBusy(button, busy) {{" in source
    assert "function renderNameCartouche(label, options = {{}}) {{" in source
    assert "function renderLinkedNameCartouche(label, options = {{}}) {{" in source
    assert '"relay_ack": build_relay_acknowledgement(' in source
    assert 'button.dataset.relayState = "sending";' in source
    assert "button.dataset.relayState = ack.state;" in source
    assert 'ack.state === "queued" ? "BBS handoff queued" : "BBS picked up"' in source
    assert '.relay-target[data-relay-state="queued"]' in source
    assert 'article.classList.add("relay-queued");' in source
    assert 'relayBadge.className = "message-state-badge relay";' in source
    assert 'queueBadge.className = "message-state-badge";' in source
    assert "relayBadge.innerHTML = renderLinkedNameCartouche(relayLabel);" in source
    assert 'const button = document.createElement("a");' in source
    assert 'button.href = target.url || "#";' in source
    assert "button.innerHTML = renderNameCartouche(target.label);" in source
    assert 'relayCallback ? "user queued relay" : "user queued"' in source
    assert 'relayCallback ? "BBS" : "You"' in source
    assert ".message.queued.relay-queued {" in source
    assert ".message-state-badge.relay {" in source


def test_relay_acknowledgement_exposes_pickup_queue_and_eta() -> None:
    module = _load_agent_console_web()

    queued = module.build_relay_acknowledgement(
        "NetOps",
        {
            "accepted": True,
            "snapshot": {
                "pending": True,
                "queue_depth": 3,
                "model_process_alive": True,
            },
        },
    )
    assert queued["state"] == "queued"
    assert queued["label"] == "Queued"
    assert queued["picked_up"] is True
    assert queued["queue_position"] == 3
    assert queued["model_alive"] is True
    assert queued["eta_label"] == "rough ETA 30 min"
    assert "queued at position 3" in queued["detail"]

    running = module.build_relay_acknowledgement(
        "Scout",
        {"accepted": True, "snapshot": {"pending": True, "queue_depth": 0}},
    )
    assert running["state"] == "running"
    assert running["label"] == "Picked up"
    assert running["eta_label"] == "running now"


def test_rendered_console_marks_bbs_relay_queue_in_dom() -> None:
    module = _load_agent_console_web()
    module.ensure_session = lambda: None
    module.current_snapshot = lambda: {
        "pending": False,
        "thread_id": "thread-demo",
        "updated_at": 1770000000,
        "services": [],
        "last_prompt": "Check the rollout failure.",
        "last_response": "Verify the failed rollout path and then continue.",
        "last_error": "",
        "pane": "[pane unavailable]",
        "logs": "[no journal output]",
        "history": [
            {
                "prompt": "Why did this rollout fail?",
                "response": "The test failed in the callback path. Verify the queue handoff and then proceed.",
                "started_at": 1770000000,
                "finished_at": 1770000010,
                "speed": "balanced",
                "detail": 3,
                "attachments": [],
            }
        ],
        "queued_prompts": [
            {
                "prompt": "BBS relay follow-up for the Switchboard lane.",
                "queued_at": 1770000020,
                "speed": "careful",
                "detail": 5,
                "attachments": [],
                "relay_callback": {
                    "relay_id": "relay-demo",
                    "target_connector_name": "Switchboard",
                    "callback_pending": True,
                },
            }
        ],
        "queue_depth": 1,
        "draft_attachments": [],
    }
    module.STATE_DIR = Path(tempfile.mkdtemp()) / "state"

    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()

    class _Headers(dict):
        def get(self, key: str, default: str = "") -> str:
            return str(super().get(key, default))

    handler.headers = _Headers({"Host": "example.test:8789"})
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.is_trusted_client = lambda: False
    handler.browser_auth_supported_for_request = lambda: False
    handler.auth_cookie_token = lambda: ""

    module.Handler.render_index(handler, {"token": ["open-sesame"]})
    rendered = handler.wfile.getvalue().decode("utf-8")

    temp_dir = Path(tempfile.mkdtemp())
    html_path = temp_dir / "console.html"
    html_path.write_text(rendered, encoding="utf-8")
    node_path = temp_dir / "assert_console_dom.js"
    node_path.write_text(
        """
const fs = require("fs");
const { JSDOM, VirtualConsole } = require(process.argv[3]);

const html = fs.readFileSync(process.argv[2], "utf8");
const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (error) => errors.push(error && error.message ? error.message : String(error)));

const dom = new JSDOM(html, {
  url: "https://example.test:8789/?token=open-sesame",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    window.fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => ({}),
      text: async () => "",
      headers: { get: () => "application/json" },
    });
    window.EventSource = function EventSource() {
      this.addEventListener = function addEventListener() {};
      this.removeEventListener = function removeEventListener() {};
      this.close = function close() {};
    };
    window.navigator.sendBeacon = () => true;
    window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {};
    window.scrollTo = function scrollTo() {};
    window.matchMedia = () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    });
  },
});

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

setTimeout(() => {
  try {
    assert(errors.length === 0, `jsdom errors: ${errors.join("\\n")}`);
    const document = dom.window.document;
    const sendLabel = document.querySelector("#ask-button-label");
    assert(sendLabel, "missing send button label");
    assert(sendLabel.textContent.trim() === "Next", `send button does not show Next: ${sendLabel.textContent.trim()}`);
    assert(!sendLabel.classList.contains("visually-hidden"), "send button label is visually hidden");

    const relayMessage = document.querySelector(".message.queued.relay-queued");
    assert(relayMessage, "missing relay queued message");
    assert(relayMessage.querySelector(".message-role").textContent.trim() === "BBS", "relay message role is not BBS");
    const roleCartouche = relayMessage.querySelector(".message-role .entity-cartouche");
    assert(roleCartouche, "relay message role is not cartouched");
    assert(roleCartouche.textContent.trim() === "BBS", "relay role cartouche does not include BBS");
    const roleCartoucheLabel = roleCartouche.querySelector(".entity-cartouche__label");
    assert(roleCartoucheLabel, "relay role cartouche does not expose a framed label");
    assert(roleCartoucheLabel.textContent.trim() === "BBS", "relay role cartouche label does not include BBS");
    const relayBadge = relayMessage.querySelector(".message-state-badge.relay");
    assert(relayBadge, "missing relay badge");
    assert(relayBadge.textContent.includes("Switchboard"), "relay badge does not include target");
    const relayCartouche = relayBadge.querySelector(".entity-cartouche");
    assert(relayCartouche, "relay target name is not cartouched");
    assert(relayCartouche.tagName === "A", "relay target cartouche is not a link");
    assert(relayCartouche.getAttribute("href"), "relay target cartouche has no href");
    assert(relayCartouche.textContent.includes("Switchboard"), "relay target cartouche does not include Switchboard");
    const relayCartoucheLabel = relayCartouche.querySelector(".entity-cartouche__label");
    assert(relayCartoucheLabel, "relay target cartouche does not expose a framed label");
    assert(relayCartoucheLabel.textContent.includes("Switchboard"), "relay target cartouche label does not include Switchboard");

    const actionKinds = Array.from(document.querySelectorAll(".reply-tail-action"))
      .map((node) => node.dataset.actionKind || node.textContent.trim());
    assert(actionKinds.includes("proceed"), "missing Proceed action");
    assert(actionKinds.includes("dig"), "missing Dig action");
    assert(actionKinds.includes("verify"), "missing Verify action");
    process.exit(0);
  } catch (error) {
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }
}, 40);
        """.strip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "node",
            str(node_path),
            str(html_path),
            str(Path(__file__).resolve().parents[1] / "node_modules" / "jsdom"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_attachment_count_phrase_summarizes_visible_queue_payload() -> None:
    module = _load_agent_console_web()

    phrase = module.attachment_count_phrase(
        [
            {
                "token": "image-1",
                "name": "a.png",
                "path": "/tmp/a.png",
                "content_type": "image/png",
                "kind": "image",
            },
            {
                "token": "block-1",
                "name": "b.txt",
                "path": "/tmp/b.txt",
                "content_type": "text/plain",
                "kind": "text",
            },
            {
                "token": "file-1",
                "name": "c.bin",
                "path": "/tmp/c.bin",
                "content_type": "application/octet-stream",
                "kind": "file",
            },
        ]
    )

    assert phrase == "1 image, 1 text block, and 1 file"


def test_template_marks_queued_attachment_counts_in_operator_copy() -> None:
    source = _agent_console_web_source()

    assert "attachmentCountPhrase(newestQueued.attachments)" in source
    assert (
        "A follow-up with ${{attachmentPhrase}} is queued behind the current run."
        in source
    )
    assert (
        "const queuedAttachmentText = attachmentCountPhrase(item.attachments);"
        in source
    )
    assert "Queued prompt{attachment_suffix} at position" in source


def test_prompt_worker_reasserts_running_state_after_prompt_lock() -> None:
    source = _agent_console_web_source()

    assert "it actually has the prompt lock" in source
    assert 'status_message=f"{AGENT_NAME} is working."' in source
    assert "running_prompt=prompt" in source
    assert "running_attachments=attachments" in source


def test_template_normalizes_message_copy_to_plain_text() -> None:
    source = _agent_console_web_source()

    assert "function normalizeCopiedText(value) {{" in source
    assert "function plainTextFromNode(node) {{" in source
    assert 'function plainTextFromRenderedMessage(article, fallback = "") {{' in source
    assert "function selectionPlainTextFromUi() {{" in source
    assert 'document.addEventListener("copy", (event) => {{' in source
    assert 'event.clipboardData.setData("text/plain", value);' in source


def test_code_block_copy_prefers_full_body_over_preview() -> None:
    source = _agent_console_web_source()

    assert (
        'block.querySelector(".code-scroll code") || block.querySelector("code")'
        in source
    )


def test_template_makes_notice_alert_cards_actionable() -> None:
    source = _agent_console_web_source()

    assert "function noticeActionForItem(item) {{" in source
    assert "function performNoticeAction(action) {{" in source
    assert "function attachNoticeActivation(node, item) {{" in source
    assert "attachNoticeActivation(card, item);" in source
    assert "attachNoticeActivation(hasInlineActions ? body : chip, item);" in source
    assert 'node.setAttribute("role", "button");' in source
    assert 'node.addEventListener("keydown", (event) => {{' in source


def test_template_polishes_loose_markdown_lists_and_section_labels() -> None:
    source = _agent_console_web_source()

    assert "function bulletLineMatch(line) {{" in source
    assert "function numberedLineMatch(line) {{" in source
    assert "function taskLineMatch(line) {{" in source
    assert "function standaloneStrongLineMatch(line) {{" in source
    assert "\\\\u2013|\\\\u2014" in source
    assert (
        'blocks.push(`<div class="section-label">${{renderInlineMarkup(strongLineMatch[1])}}</div>`);'
        in source
    )
    assert ".message-body .section-label," in source
    assert ".message-body li::marker," in source


def test_template_promotes_high_signal_entities_into_cartouches() -> None:
    source = _agent_console_web_source()

    assert "INLINE_HOST_ENTITY_ALIASES" in source
    assert "INLINE_TUI_ENTITY_DEFS" in source
    assert "INLINE_BOT_ENTITY_DEFS" in source
    assert "const INLINE_ENTITY_DEFS =" in source
    assert "const INLINE_ENTITY_ALIAS_MAP =" in source
    assert "function buildInlineEntityEntries(defs) {{" in source
    assert "function indexInlineEntityAliasMap(entries) {{" in source
    assert "function indexInlineEntityMap(entries) {{" in source
    assert "function highlightInlineEntities(text) {{" in source
    assert "function renderNameCartouche(label, options = {{}}) {{" in source
    assert "function renderLinkedNameCartouche(label, options = {{}}) {{" in source
    assert "function tuiHrefForLabel(label) {{" in source
    assert 'class="entity-cartouche"' in source
    assert 'data-label="{html.escape(str(item["label"]))}"' in source
    assert '_render_name_cartouche(str(item["label"]), kind="bot"' in source
    assert ".message-body .entity-cartouche," in source
    assert ".message-role .entity-cartouche," in source
    assert ".message-state-badge .entity-cartouche," in source
    assert ".entity-cartouche__label {" in source
    assert '.entity-cartouche[data-kind="tui"],' in source
    assert '.entity-cartouche[data-alias="true"],' in source
    assert 'data-alias="true" data-alias-for=' in source
    assert "--cartouche-rail" in source
    assert "display: inline-grid;" in source
    assert '<span class="entity-cartouche__label">' in source
    assert 'data-kind="${{escapeHtml(kind)}}"' in source
    assert 'data-compact="true"' in source
    assert 'data-mention="true"' in source
    assert 'const mentionable = baseKind !== "host";' in source
    assert (
        "renderEntityCartouche({{ ...base, mark, tone }}, "
        "`@${{label}}`, {{ mention: mentionable }})" in source
    )
    assert '"toy-box.home.arpa"' in source
    assert '"toy-box.tail00000.ts.net"' in source
    assert '"private.home.example.test"' in source
    assert '"192.168.0.241"' in source
    assert '"Norman Prime"' in source
    assert '"Scout / Ranger"' in source
    assert '"Phone Ops"' in source
    assert '"Norman Ops"' in source
    assert '"Diamond ROC"' in source
    assert '"me"' in source
    assert "home\\.lollie\\.org" in source
    assert "tail[0-9]+\\.ts\\.net" in source
    assert "renderSwitcherHostCartouche(item.host)" in source
    assert (
        'renderNameCartouche(label, {{ kind: "host", tone: "host", compact: true }})'
        in source
    )
    assert (
        'renderNameCartouche(item.label, {{ kind: "bot", tone: "bot", group: item.group }})'
        in source
    )
    assert ".switcher-item-host::before" in source


def test_initial_inline_markup_marks_tui_alias_host_and_people_cartouches() -> None:
    module = _load_agent_console_web()

    rendered = module._render_initial_inline_markup(
        "Norman Prime, Subprime, Scout / Ranger, Phone Ops, Norman Ops, "
        "Control Plane, Diamond ROC, Glimpser / Eyebat, toy-box.home.arpa, "
        "me, Example",
        token="",
        profile="",
        route="",
    )

    assert rendered.count('data-kind="tui"') >= 8
    assert 'data-kind="host"' in rendered
    assert 'data-kind="person"' in rendered
    assert 'data-group="operator" data-alias="true"' in rendered
    assert 'data-group="family"' in rendered
    assert 'data-alias-for="Norman Subprime"' in rendered
    assert 'data-alias-for="Eyebat"' in rendered
    assert ">Scout / Ranger<" in rendered
    assert ">toy-box.home.arpa<" in rendered


def test_template_exposes_context_save_affordance() -> None:
    source = _agent_console_web_source()

    assert 'id="context-save-button"' in source
    assert 'id="context-save-menu-button"' in source
    assert "function buildContextSavePrompt(context) {" in source
    assert "function handleContextSaveAction(button) {" in source
    assert (
        'const saveLabel = context.tone === "danger" ? "Save now" : "Save";' in source
    )
    assert "button.dataset.suggestion = savePrompt;" in source
    assert 'el.contextSaveButton.addEventListener("click"' in source
    assert 'el.contextSaveMenuButton.addEventListener("click"' in source


def test_template_persists_prompt_drafts_for_console_recovery() -> None:
    source = _agent_console_web_source()

    assert "const PROMPT_DRAFT_STORAGE_KEY =" in source
    assert "const PROMPT_DRAFT_MAX_AGE_MS =" in source
    assert "function safeStorageRemove(key) {{" in source
    assert "function loadPromptDraft() {{" in source
    assert "function persistPromptDraft(value = el.promptInput.value) {{" in source
    assert "function restorePromptDraft() {{" in source
    assert "function clearPromptDraft() {{" in source
    assert "persistPromptDraft(el.promptInput.value);" in source
    assert "clearPromptDraft();" in source
    assert 'window.addEventListener("beforeunload", () => {{' in source
    assert 'if (document.visibilityState === "hidden") {{' in source
    assert "restorePromptDraft();" in source


def test_template_exposes_status_capsule_strip() -> None:
    source = _agent_console_web_source()

    assert 'id="kpi-strip"' in source
    assert 'id="system-runtime-metrics"' in source
    assert "function normalizeKpiTone(value) {" in source
    assert "function normalizeResourceKpiMeters(snapshot) {" in source
    assert "function usageCapsuleState(snapshot) {" in source
    assert "function buildStatusCapsules(snapshot) {" in source
    assert "function renderStatusCapsules(snapshot) {" in source
    assert "function renderSystemRuntimeMetrics(snapshot) {" in source
    assert "HOUSEBOT_CODEX_RESOURCE_METER_PATH" in source
    assert "def load_resource_meter_file() -> dict[str, Any]:" in source
    assert "snapshot.resource_meter || {{}}" in source
    assert 'if (clean === "danger" || clean === "alert") return "alert";' in source
    assert "return [...adapterCapsules, ...fallbackCapsules].slice(0, 4);" in source
    assert 'button.dataset.kpiAction = String(item.action || "system");' in source
    assert 'const action = String(capsule.dataset.kpiAction || "system");' in source
    assert 'if (action === "notices") {' in source


def test_tui_uses_render_caches_and_background_transport_backoff() -> None:
    source = _agent_console_web_source()

    assert "renderCache: {{" in source
    assert "function conversationRenderSignature(snapshot) {{" in source
    assert "if (state.renderCache.conversation === renderKey) {{" in source
    assert "function disconnectStream() {{" in source
    assert "function syncLiveTransport() {{" in source
    assert "document.hidden" in source
    assert "? (state.snapshot.pending ? 12000 : 30000)" in source
    assert (
        'setTransportState(state.snapshot.pending ? "Background · waiting" : "Background", false);'
        in source
    )
    assert "syncLiveTransport();" in source


def test_home_prime_uses_adaptive_poll_loops() -> None:
    source = _home_js_source()

    assert "const adaptiveTimers = new Map();" in source
    assert (
        "function startAdaptiveLoop(name, task, visibleDelayMs, hiddenDelayMs = visibleDelayMs)"
        in source
    )
    assert "startAdaptiveLoop('prime-panels'" in source
    assert "startAdaptiveLoop('fleet'" in source
    assert "startAdaptiveLoop('traffic'" in source
    assert "startAdaptiveLoop('attention'" in source


def test_execute_codex_prompt_captures_turn_usage() -> None:
    module = _load_agent_console_web()
    state_dir = Path(tempfile.mkdtemp()) / "state"
    module.STATE_DIR = state_dir
    module.THREAD_ID_PATH = state_dir / "thread_id.txt"
    original_popen = module.subprocess.Popen

    class _FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdout, stderr, env, start_new_session):
            self.cmd = cmd
            assert text is True
            assert stdout == module.subprocess.PIPE
            assert stderr == module.subprocess.PIPE
            assert start_new_session is True
            assert env["CODEX_HOME"] == module.CODEX_HOME
            (state_dir / "last_message.txt").parent.mkdir(parents=True, exist_ok=True)
            (state_dir / "last_message.txt").write_text("ok", encoding="utf-8")

        def communicate(self):
            return (
                '{"type":"thread.started","thread_id":"thread-usage"}\n'
                '{"type":"turn.completed","usage":{"input_tokens":321,"cached_input_tokens":45,"output_tokens":29}}\n',
                "",
            )

    try:
        module.subprocess.Popen = _FakePopen
        response, error_text, thread_id, usage = module._execute_codex_prompt(
            "hello", "slow", 1, []
        )
    finally:
        module.subprocess.Popen = original_popen

    assert response == "ok"
    assert error_text == ""
    assert thread_id == "thread-usage"
    assert usage["input_tokens"] == 321
    assert usage["cached_input_tokens"] == 45
    assert usage["output_tokens"] == 29
    assert usage["total_tokens"] == 350


def test_execute_codex_prompt_times_out_and_terminates_child() -> None:
    module = _load_agent_console_web()
    state_dir = Path(tempfile.mkdtemp()) / "state"
    module.STATE_DIR = state_dir
    module.STATUS_PATH = state_dir / "status.json"
    module.THREAD_ID_PATH = state_dir / "thread_id.txt"
    module.WEB_PROMPT_TIMEOUT_SECONDS = 1
    module.WEB_PROMPT_TIMEOUT_GRACE_SECONDS = 0.1
    original_popen = module.subprocess.Popen
    original_terminate = module.terminate_process_group
    killed: list[tuple[int, int]] = []

    class _TimeoutPopen:
        pid = 23456

        def __init__(self, cmd, text, stdout, stderr, env, start_new_session):
            self.cmd = cmd
            self.returncode = None
            self.calls = 0
            assert text is True
            assert stdout == module.subprocess.PIPE
            assert stderr == module.subprocess.PIPE
            assert start_new_session is True

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise module.subprocess.TimeoutExpired(
                    self.cmd,
                    timeout,
                    output='{"type":"thread.started","thread_id":"thread-timeout"}\n',
                    stderr="still running",
                )
            self.returncode = -15
            return "", "terminated"

    def _fake_terminate(pid: int, pgid: int) -> bool:
        killed.append((pid, pgid))
        return True

    try:
        module.subprocess.Popen = _TimeoutPopen
        module.terminate_process_group = _fake_terminate
        response, error_text, thread_id, usage = module._execute_codex_prompt(
            "status?", "slow", 1, []
        )
    finally:
        module.subprocess.Popen = original_popen
        module.terminate_process_group = original_terminate

    assert response == ""
    assert error_text == (
        f"{module.WEB_PROMPT_TIMED_OUT_PREFIX}1 seconds and was terminated."
    )
    assert thread_id == "thread-timeout"
    assert killed == [(23456, 23456)]
    assert usage["total_tokens"] == 0


def test_usage_snapshot_tracks_recent_burn() -> None:
    module = _load_agent_console_web()
    state_dir = Path(tempfile.mkdtemp()) / "state"
    module.STATE_DIR = state_dir
    module.USAGE_PATH = state_dir / "usage.jsonl"

    now = int(time.time())
    module.append_usage_entry(
        started_at=now - module.USAGE_WINDOW_SECONDS - 180,
        finished_at=now - module.USAGE_WINDOW_SECONDS - 120,
        thread_id="older",
        speed="slow",
        detail=1,
        success=False,
        usage={"input_tokens": 50, "cached_input_tokens": 10, "output_tokens": 5},
    )
    module.append_usage_entry(
        started_at=now - 90,
        finished_at=now - 60,
        thread_id="recent",
        speed="fast",
        detail=2,
        success=True,
        usage={"input_tokens": 120, "cached_input_tokens": 30, "output_tokens": 18},
    )

    snapshot = module.usage_snapshot(thread_id="recent")

    assert snapshot["tracked"] is True
    assert snapshot["totals"]["turns"] == 2
    assert snapshot["totals"]["successful_turns"] == 1
    assert snapshot["totals"]["failed_turns"] == 1
    assert snapshot["totals"]["total_tokens"] == 193
    assert snapshot["last_24h"]["turns"] == 1
    assert snapshot["last_24h"]["total_tokens"] == 138
    assert snapshot["current_thread"]["turns"] == 1
    assert snapshot["current_thread"]["total_tokens"] == 138
    assert snapshot["last_turn"]["thread_id"] == "recent"
    assert snapshot["last_turn"]["total_tokens"] == 138


def test_initial_context_meter_flags_save_soon_for_heavy_sessions() -> None:
    module = _load_agent_console_web()

    meter = module._initial_context_meter(
        {
            "history": [{} for _ in range(24)],
            "usage": {
                "totals": {
                    "turns": 24,
                    "total_tokens": 94_200,
                },
                "last_24h": {
                    "total_tokens": 64_000,
                },
            },
            "queue_depth": 1,
            "pending": False,
            "running_prompt": "",
        }
    )

    assert meter["hidden"] is False
    assert meter["tone"] == "danger"
    assert meter["label"] == "Save soon"
    assert meter["fill_pct"] >= 92
    assert "94,200 tracked tokens" in meter["title"]


def test_resource_meter_normalizes_lane_kpis_and_chat_queue() -> None:
    module = _load_agent_console_web()

    meter = module.normalize_resource_meter(
        {
            "kpi_meters": [
                {
                    "id": "accepted",
                    "label": "Accepted",
                    "value": 10,
                    "unit": "requests",
                    "tone": "watch",
                    "detail": "Accepted means received, not done.",
                    "source": "agent_requests_latest.json",
                    "updated_at": "2026-05-09T00:00:00Z",
                    "stale_after_seconds": 900,
                },
                {"id": "bad", "label": "   ", "value": 99},
                {"id": "pp_queued", "label": "PP Queued", "value": 73},
                {
                    "id": "pp_blocked",
                    "label": "PP Blocked",
                    "value": 84,
                    "tone": "danger",
                },
                {"id": "oldest", "label": "Oldest", "value": "2h"},
                {"id": "extra", "label": "Extra", "value": 1},
            ],
        },
        snapshot_at=1778284800,
        pending=True,
        queue_depth=2,
        running_prompt="check scout",
    )

    assert meter["version"] == "norman.queue-resource-meter.v1"
    assert meter["read_only"] is True
    assert meter["conversation"]["running"] == 1
    assert meter["conversation"]["queued"] == 2
    assert meter["conversation"]["pending"] is True
    assert [item["id"] for item in meter["kpi_meters"]] == [
        "accepted",
        "pp_queued",
        "pp_blocked",
        "oldest",
    ]
    assert meter["kpi_meters"][0]["tone"] == "watch"
    assert meter["kpi_meters"][2]["tone"] == "danger"


def test_resource_meter_file_loader_reads_adapter_payload(tmp_path: Path) -> None:
    module = _load_agent_console_web()
    resource_meter_path = tmp_path / "resource_meter.json"
    resource_meter_path.write_text(
        '{"kpi_meters": [{"id": "accepted", "label": "Accepted", "value": 10}]}',
        encoding="utf-8",
    )
    original_path = module.RESOURCE_METER_PATH
    try:
        module.RESOURCE_METER_PATH = resource_meter_path
        payload = module.load_resource_meter_file()
    finally:
        module.RESOURCE_METER_PATH = original_path

    assert payload["kpi_meters"][0]["id"] == "accepted"
    assert payload["kpi_meters"][0]["value"] == 10


def test_prime_credits_ui_surfaces_usage_burn() -> None:
    source = _home_js_source()

    assert "function formatPrimeTokenCompact(value)" in source
    assert "24h burn" in source
    assert "usage_window_total_tokens" in source
    assert "prime-credit-card__stats" in source


def test_prime_audit_ui_surfaces_centralized_tui_forensics() -> None:
    styles = _styles_source()
    template = _index_template_source()
    source = _home_js_source()

    assert "Audit" in template
    assert 'id="home-prime-audit-status"' in template
    assert 'id="home-prime-audit-summary"' in template
    assert 'id="home-prime-audit"' in template
    assert "function primeAuditTone(item)" in source
    assert "function primeAuditPrompt(item)" in source
    assert "function renderPrimeAudit(payload)" in source
    assert "function loadPrimeAudit({ silent = false } = {})" in source
    assert "/api/v1/tmux/control/audit?limit=12" in source
    assert 'data-prime-audit-session="' in source
    assert ".home-prime__audit-summary" in styles
    assert ".prime-audit-card {" in styles
    assert ".prime-audit-card__severity--danger" in styles


def test_home_prime_surface_reuses_tighter_tui_style_language() -> None:
    styles = _styles_source()
    template = _index_template_source()
    source = _home_js_source()

    assert "body.home-mode .navbar.site-banner" in styles
    assert ".home-prime__hero {" in styles
    assert ".home-prime__dock {" in styles
    assert ".home-prime__hero::after {" in styles
    assert ".home-prime__hero-aside::before {" in styles
    assert ".home-prime__focus::before {" in styles
    assert ".home-prime__section::after {" in styles
    assert ".home-prime__actions .btn {" in styles
    assert ".home-prime__ops-head {" in styles
    assert ".home-prime__ops-tools .btn {" in styles
    assert ".home-prime__chat-items {" in styles
    assert ".home-prime__audit-items {" in styles
    assert ".prime-desk__chat {" in styles
    assert ".prime-desk__chat-log {" in styles
    assert ".prime-desk__chat-message {" in styles
    assert ".prime-desk__chat-compose-meta {" in styles
    assert ".prime-chat-card {" in styles
    assert ".home-prime .btn-primary:hover," in styles
    assert "Coordination Surface" in template
    assert "Switchboard" in template
    assert ">Open Switchboard</a>" in template
    assert 'id="home-prime-chats"' in template
    assert 'id="home-prime-chats-status"' in template
    assert 'id="home-prime-chat-log"' in template
    assert 'id="home-prime-chat-input"' in template
    assert 'id="home-prime-chat-form"' in template
    assert 'id="home-prime-chat-hint"' in template
    assert "function renderPrimeChats(items)" in source
    assert "function renderPrimeAudit(payload)" in source
    assert "function primeChatPreview(item)" in source
    assert "function loadPrimeNormanChat({ silent = false } = {})" in source
    assert "function sendPrimeNormanMessage(content)" in source
    assert (
        "function seedPrimeNormanDraft(prompt, { force = false, announce = false } = {})"
        in source
    )
    assert "function findPrimeNormanChannel(channels)" in source
    assert "console subprime" in source
    assert "function syncPrimeOpsToChat(item)" in source
    assert 'data-prime-chat-session="' in source
    assert "Tracing this source in Workers" in source
    assert ".prime-chat-card.is-selected," in styles
    assert ".prime-op-card.is-selected {" in styles
    assert "Latest reply" in source
    assert 'data-prime-compose-draft="' in source
    assert 'data-prime-chat-send="' in source
    assert "homePrimeChatInput?.addEventListener('keydown'" in source
    assert (
        "event.shiftKey || event.altKey || event.ctrlKey || event.metaKey || event.isComposing"
        in source
    )
    assert "homePrimeChatForm.requestSubmit()" in source
    assert "Enter sends" in template
    assert "Shift+Enter newline" in template
    assert ">Norman chat</button>" in source
    assert ">Use here</button>" in source
    assert ">Editor</a>" in source
    assert "Send to Switchboard" in template


def test_base_nav_splits_chat_and_dashboard_routes() -> None:
    routes = (Path(__file__).resolve().parents[1] / "app" / "app_routes.py").read_text(
        encoding="utf-8"
    )
    template = _base_template_source()

    assert (
        'href="/editor.html?pane=conversation&amp;thread=console+-+Norman&amp;shell=prime"'
        in template
    )
    assert ">Chat</a>" in template
    assert 'href="/dashboard.html"' in template
    assert ">Dashboard</a>" in template
    assert (
        "brand-sub\">{% if active_page == 'home' %}Prime{% else %}Chat{% endif %}"
        in template
    )
    assert '@app_routes.get("/dashboard")' in routes
    assert '@app_routes.get("/dashboard.html")' in routes
    assert (
        "return RedirectResponse(url=_norman_chat_redirect_url(request), status_code=307)"
        in routes
    )


def test_messages_template_embeds_prime_layer_for_super_tui_mode() -> None:
    template = _messages_log_template_source()
    styles = _styles_source()
    js = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "js"
        / "messages_log.js"
    ).read_text(encoding="utf-8")

    assert "messages-page--super" in template
    assert (
        '<a class="messages-super-cartouche" href="/bot/norman/" aria-label="Norman">'
        in template
    )
    assert (
        '<span class="messages-super-cartouche__mark" aria-hidden="true">N1</span>'
        in template
    )
    assert ".messages-super-cartouche {" in styles
    assert ".messages-super-cartouche:hover" in styles
    assert ".messages-super-cartouche::after" in styles
    assert 'id="messages-prime-layer-toggle"' in template
    assert 'id="messages-prime-layer-frame"' in template
    assert 'src="{{ dashboard_embed_url }}"' in template
    assert "Embedded Switchboard" in template
    assert "function initSuperTuiPrimeLayer()" in js
    assert "SUPER_TUI_PRIME_OPEN_KEY" in js
    assert ".messages-prime-layer {" in styles
    assert "body.embed-mode" in styles


def test_template_exposes_context_meter_save_hint() -> None:
    source = _agent_console_web_source()

    assert 'id="context-meter-chip"' in source
    assert 'id="context-meter-status"' in source
    assert "function contextMeterState(snapshot)" in source
    assert "function renderContextMeter(snapshot)" in source
    assert "Save soon" in source
    assert "Heuristic only; use it as a save/compact hint" in source


def test_composer_upload_icon_uses_composer_inline_action_selector() -> None:
    source = _agent_console_web_source()

    assert ".composer-inline-action[data-icon]::before," in source
    assert ".inline-action[data-icon]::before," not in source


def test_composer_upload_menu_is_not_clipped_by_input_shell() -> None:
    source = _agent_console_web_source()
    match = re.search(
        r"\.composer-input-shell \{\{(?P<body>.*?)\n    \}\}", source, re.S
    )
    assert match
    shell_rule = match.group("body")

    assert "overflow: visible;" in shell_rule
    assert "overflow: hidden;" not in shell_rule
    assert 'id="composer-upload-button"' in source
    assert 'id="composer-upload-menu"' in source


def test_render_index_emits_escaped_newline_sequences_in_inline_js() -> None:
    module = _load_agent_console_web()
    module.ensure_session = lambda: None
    module.current_snapshot = lambda: {
        "pending": False,
        "thread_id": "thread-demo",
        "updated_at": 0,
        "services": [],
        "last_prompt": "[no prompt yet]",
        "last_response": "[no response yet]",
        "last_error": "[none]",
        "pane": "[pane unavailable]",
        "logs": "[no journal output]",
        "history": [],
        "queued_prompts": [],
        "queue_depth": 0,
        "draft_attachments": [],
    }
    module.STATE_DIR = Path(tempfile.mkdtemp()) / "state"

    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()

    class _Headers(dict):
        def get(self, key: str, default: str = "") -> str:
            return str(super().get(key, default))

    handler.headers = _Headers({"Host": "example.test:8789"})
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.is_trusted_client = lambda: False
    handler.browser_auth_supported_for_request = lambda: False
    handler.auth_cookie_token = lambda: ""

    module.Handler.render_index(handler, {"token": ["open-sesame"]})
    rendered = handler.wfile.getvalue().decode("utf-8")

    assert 'replace(/\\r\\n/g, "\\n")' in rendered
    assert 'replace(/\\n/g, "<br>")' in rendered
    assert 'join("\\n") || "[no log tail yet]"' in rendered


def test_render_index_emits_javascript_that_passes_node_syntax_check() -> None:
    module = _load_agent_console_web()
    module.ensure_session = lambda: None
    module.current_snapshot = lambda: {
        "pending": False,
        "thread_id": "thread-demo",
        "updated_at": 0,
        "services": [],
        "last_prompt": "[no prompt yet]",
        "last_response": "[no response yet]",
        "last_error": "[none]",
        "pane": "[pane unavailable]",
        "logs": "[no journal output]",
        "history": [],
        "queued_prompts": [],
        "queue_depth": 0,
        "draft_attachments": [],
    }
    module.STATE_DIR = Path(tempfile.mkdtemp()) / "state"

    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()

    class _Headers(dict):
        def get(self, key: str, default: str = "") -> str:
            return str(super().get(key, default))

    handler.headers = _Headers({"Host": "example.test:8789"})
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.is_trusted_client = lambda: False
    handler.browser_auth_supported_for_request = lambda: False
    handler.auth_cookie_token = lambda: ""

    module.Handler.render_index(handler, {"token": ["open-sesame"]})
    rendered = handler.wfile.getvalue().decode("utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", rendered, re.S)
    script_text = "\n\n".join(scripts)

    script_path = Path(tempfile.mkdtemp()) / "rendered_console.js"
    script_path.write_text(script_text, encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_render_index_anchors_live_edge_to_latest_message_node() -> None:
    module = _load_agent_console_web()
    module.ensure_session = lambda: None
    module.current_snapshot = lambda: {
        "pending": False,
        "thread_id": "thread-demo",
        "updated_at": 0,
        "services": [],
        "last_prompt": "[no prompt yet]",
        "last_response": "[no response yet]",
        "last_error": "[none]",
        "pane": "[pane unavailable]",
        "logs": "[no journal output]",
        "history": [],
        "queued_prompts": [],
        "queue_depth": 0,
        "draft_attachments": [],
    }
    module.STATE_DIR = Path(tempfile.mkdtemp()) / "state"

    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()

    class _Headers(dict):
        def get(self, key: str, default: str = "") -> str:
            return str(super().get(key, default))

    handler.headers = _Headers({"Host": "example.test:8789"})
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.is_trusted_client = lambda: False
    handler.browser_auth_supported_for_request = lambda: False
    handler.auth_cookie_token = lambda: ""

    module.Handler.render_index(handler, {"token": ["open-sesame"]})
    rendered = handler.wfile.getvalue().decode("utf-8")

    assert "function latestConversationNode()" in rendered
    assert 'latest.scrollIntoView({ block: "end", inline: "nearest" });' in rendered


def test_post_auth_self_check_advances_banner_and_trust_prompt(monkeypatch) -> None:
    module = _load_agent_console_web()

    panes = iter(
        [
            "Signed in with your ChatGPT account\nPress Enter to continue",
            "Do you trust the contents of this directory?\n1. Yes, continue\n2. No, quit\nPress Enter to continue",
            "OpenAI Codex (v0)\ndirectory: /home/operator/code/control_plane",
        ]
    )
    sent: list[list[str]] = []

    def _capture() -> str:
        try:
            return next(panes)
        except StopIteration:
            return "OpenAI Codex (v0)\ndirectory: /home/operator/code/control_plane"

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    module.ensure_session = lambda: True
    module.capture_pane = _capture
    module.read_text = lambda _path, default="": default
    module.run = lambda cmd, input_text=None, check=False: sent.append(cmd) or _Result()
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    ok, detail = module._run_post_auth_self_check(timeout=0.2)

    assert ok is True
    assert "Self-check passed" in detail
    assert any(cmd[-1] == "Enter" for cmd in sent)
    assert any(cmd[-2:] == ["1", "Enter"] for cmd in sent)


def test_build_file_href_preserves_line_fragment() -> None:
    module = _load_agent_console_web()

    rendered = module.build_file_href(
        token="open-sesame",
        path="/tmp/demo.py#L14",
        profile="personal-2",
        route="host",
    )

    assert "path=%2Ftmp%2Fdemo.py" in rendered
    assert "%23L14" not in rendered
    assert rendered.endswith("#L14")


def test_profile_alias_paths_redirect_to_query_profile() -> None:
    module = _load_agent_console_web()

    assert module.profile_alias_name_from_path("/profile-slate") == "slate"
    assert module.profile_alias_name_from_path("/profile/evergreen") == "evergreen"
    assert module.profile_alias_name_from_path("/profile-nope") == ""

    href = module.build_profile_alias_href(
        "/profile-slate",
        {"token": ["open-sesame"], "route": ["host"]},
    )
    assert href == "/?token=open-sesame&route=host&profile=slate"


def test_render_index_keeps_composer_shortcuts_out_of_visible_chrome() -> None:
    source = _agent_console_web_source()

    assert "composer-shortcut-hint" not in source
    assert "Enter sends" not in source
    assert "Shift+Enter newline" not in source
    assert "topbar-version" in source
    assert "Console UI version" in source
    assert "status-action-button" in source
    assert "status-action-panel" in source
    assert "Ask status" in source
    assert "Handle it" in source
    assert 'clientPath("/api/kpis")' in source
    assert 'class="primary composer-send" data-icon="→"' in source
    assert 'class="composer-send-label">Next</span>' in source
    assert 'state.snapshot.pending ? "Queue" : "Next"' in source


def test_agent_console_template_exposes_per_agent_microtexture_tokens() -> None:
    source = _agent_console_web_source()

    assert "AGENT_TEXTURE_OVERRIDES" in source
    assert "def agent_texture_vars_css" in source
    assert "{agent_texture_vars_css(AGENT_SLUG)}" in source
    assert '"norman": {' in source
    assert '"gold-book": {' in source
    assert '"platinum-standard": {' in source
    assert '"null-agent": {' in source
    assert '"earlybird": "work"' in source
    assert '"theseus": "personal"' in source
    assert '"mls": "work"' in source
    assert '"pefb": "private"' in source
    assert "repeating-linear-gradient(\n          var(--texture-angle)" in source
    assert "var(--brand-wash-opacity)" in source
    assert "var(--focus-detail-opacity)" in source
    assert '"composer-detail-opacity"' in source
    assert '"composer-cross-detail-opacity"' in source
    assert '"message-detail-opacity"' in source
    assert "var(--composer-detail-opacity)" not in source
    assert "var(--composer-cross-detail-opacity)" not in source
    assert "var(--message-detail-opacity)" not in source
    assert "var(--agent-accent-3)" in source


def test_agent_console_template_exposes_per_agent_typography_tokens() -> None:
    source = _agent_console_web_source()

    assert "AGENT_FONT_OVERRIDES" in source
    assert "WORK_FONT_VARS" in source
    assert '"null-agent": {' in source
    assert "--type-brand-size" in source
    assert "font-size: var(--type-brand-size)" in source
    assert "font-size: var(--type-reading-size)" in source
    assert "font-family: var(--font-brand)" in source
    assert "font-family: var(--font-label)" in source
    assert "font-size: clamp" not in source
    assert "letter-spacing: -" not in source


def test_build_console_and_file_href_support_prefixes() -> None:
    module = _load_agent_console_web()

    console_href = module.build_console_href(
        token="open-sesame",
        profile="slate",
        route="host",
        prefix="/bot/platinum",
    )
    file_href = module.build_file_href(
        token="open-sesame",
        path="/tmp/demo.py#L9",
        profile="slate",
        route="host",
        prefix="/bot/platinum",
    )

    assert console_href.startswith("/bot/platinum/?")
    assert "token=open-sesame" in console_href
    assert file_href.startswith("/bot/platinum/api/file?")
    assert file_href.endswith("#L9")


def test_entity_mark_for_label_prefers_clear_agent_monograms() -> None:
    module = _load_agent_console_web()

    assert module.entity_mark_for_label("d.ace") == "DA"
    assert module.entity_mark_for_label("Control Plane") == "CP"
    assert module.entity_mark_for_label("theseus") == "TH"
    assert module.console_tab_title("Theseus Console") == "Theseus"


def test_render_initial_inline_markup_links_internal_markdown_targets() -> None:
    module = _load_agent_console_web()

    rendered = module._render_initial_inline_markup(
        "See [demo.py]\n(/tmp/demo.py#L14).",
        token="open-sesame",
        profile="personal-2",
        route="host",
    )

    assert 'class="file-link"' in rendered
    assert "/api/file?" in rendered
    assert "#L14" in rendered
    assert "[demo.py]" not in rendered


def test_render_initial_inline_markup_sanitizes_raw_html_anchor_links() -> None:
    module = _load_agent_console_web()

    rendered = module._render_initial_inline_markup(
        '<a href="http://norman.home.arpa:8788/?token=secret-token" target="_blank" rel="noreferrer">'
        "http://norman.home.arpa:8788/?token=secret-token"
        "</a>",
        token="open-sesame",
        profile="personal-2",
        route="host",
    )

    assert 'href="http://norman.home.arpa:8788/?token=secret-token"' in rendered
    assert 'target="_blank" rel="noreferrer"' in rendered
    assert "http://norman.home.arpa:8788/?token=••••••" in rendered
    assert "target=&quot;_blank&quot;" not in rendered
    assert "secret-spoiler" not in rendered


def test_render_initial_inline_markup_masks_query_values_without_breaking_href() -> (
    None
):
    module = _load_agent_console_web()

    rendered = module._render_initial_inline_markup(
        "See http://norman.home.arpa:8788/?token=secret-token for the live desk.",
        token="open-sesame",
        profile="personal-2",
        route="host",
    )

    assert 'href="http://norman.home.arpa:8788/?token=secret-token"' in rendered
    assert "token=••••••" in rendered
    assert "secret-spoiler" not in rendered


def test_render_initial_inline_markup_formats_inline_code_segments() -> None:
    module = _load_agent_console_web()

    rendered = module._render_initial_inline_markup(
        "- `Management` `acct-management`\n- `Log Archive` `acct-log-archive`",
        token="open-sesame",
        profile="personal-2",
        route="host",
    )

    assert "<code>Management</code>" in rendered
    assert "<code>acct-management</code>" in rendered
    assert "`Management`" not in rendered
    assert "`acct-management`" not in rendered


def test_render_index_emits_prefixed_client_paths_for_proxied_bots() -> None:
    module = _load_agent_console_web()
    module.ensure_session = lambda: None
    module.current_snapshot = lambda: {
        "pending": False,
        "thread_id": "thread-demo",
        "updated_at": 0,
        "services": [],
        "last_prompt": "[no prompt yet]",
        "last_response": "[no response yet]",
        "last_error": "[none]",
        "pane": "[pane unavailable]",
        "logs": "[no journal output]",
        "history": [],
        "queued_prompts": [],
        "queue_depth": 0,
        "draft_attachments": [],
    }
    module.STATE_DIR = Path(tempfile.mkdtemp()) / "state"

    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()

    class _Headers(dict):
        def get(self, key: str, default: str = "") -> str:
            return str(super().get(key, default))

    handler.headers = _Headers(
        {
            "Host": "norman.home.arpa",
            "X-Forwarded-Prefix": "/bot/platinum",
        }
    )
    handler.client_address = ("127.0.0.1", 443)
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.is_trusted_client = lambda: False
    handler.browser_auth_supported_for_request = lambda: False
    handler.auth_cookie_token = lambda: ""

    module.Handler.render_index(handler, {"token": ["open-sesame"]})
    rendered = handler.wfile.getvalue().decode("utf-8")

    assert 'const REQUEST_BASE_PATH = "/bot/platinum";' in rendered
    assert "function clientPath(path)" in rendered
    assert 'action="/bot/platinum/ask"' in rendered
    assert 'href="/bot/platinum/auth/browser/callback"' in rendered
    assert 'href="/bot/platinum/healthz' in rendered
    assert 'clientPath("/api/file")' in rendered


def test_render_file_preview_html_emits_line_anchor_targets() -> None:
    module = _load_agent_console_web()

    rendered = module.render_file_preview_html("alpha\nbeta\n")

    assert 'id="L1"' in rendered
    assert 'href="#L2"' in rendered
    assert "alpha" in rendered
    assert "beta" in rendered


def test_render_directory_view_exposes_copy_path_button() -> None:
    module = _load_agent_console_web()
    tempdir = Path(tempfile.mkdtemp())
    (tempdir / "alpha.txt").write_text("alpha", encoding="utf-8")
    handler = _make_handler(module)

    module.Handler.render_directory_view(handler, tempdir, {"profile": ["slate"]})
    rendered = handler.wfile.getvalue().decode("utf-8")

    assert "Copy path" in rendered
    assert 'data-copy-value="' in rendered
    assert "render_file_copy_script" not in rendered
    assert "function copyText(value, button)" in rendered


def test_render_file_view_exposes_copy_path_and_copy_text_buttons() -> None:
    module = _load_agent_console_web()
    tempdir = Path(tempfile.mkdtemp())
    target = tempdir / "notes.md"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    handler = _make_handler(module)

    module.Handler.render_file_view(
        handler,
        target,
        "text/markdown; charset=utf-8",
        target.stat(),
        {"profile": ["slate"]},
    )
    rendered = handler.wfile.getvalue().decode("utf-8")

    assert 'id="copy-path-button"' in rendered
    assert 'id="copy-preview-button"' in rendered
    assert 'data-copy-target="file-copy-source"' in rendered
    assert 'id="file-copy-source"' in rendered
    assert "Copy text" in rendered


def test_semantic_console_group_normalizes_variant_labels() -> None:
    module = _load_agent_console_web()

    assert module.semantic_console_group("Personal 2") == "personal"
    assert module.semantic_console_group("work-special") == "work"
    assert module.semantic_console_group("Shared Infra") == "shared"


def test_parse_console_links_preserves_optional_focus_metadata() -> None:
    module = _load_agent_console_web()

    rendered = module.parse_console_links(
        '[{"label":"Mac VNC","group":"Personal 2","url":"remmina://castle","featured":true,"lane":"make","note":"Mac fallback","priority":9}]'
    )

    assert rendered == [
        {
            "label": "Mac VNC",
            "group": "Personal 2",
            "url": "remmina://castle",
            "lan_url": "",
            "featured": True,
            "priority": 9,
            "lane": "make",
            "note": "Mac fallback",
        }
    ]


def test_console_link_anchor_attrs_keeps_custom_scheme_local() -> None:
    module = _load_agent_console_web()

    assert module.console_link_anchor_attrs("remmina://castle") == ""
    assert "target" in module.console_link_anchor_attrs("https://example.com")


def test_build_console_focus_lanes_prioritizes_make_before_operate() -> None:
    module = _load_agent_console_web()

    lanes = module.build_console_focus_lanes(
        [
            {
                "label": "Workbench",
                "group": "Norman",
                "group_slug": "norman",
                "tone_group": "norman",
                "url": "/api/file?path=%2Ftmp",
                "lane": "make",
                "featured": True,
                "priority": 200,
                "source": "local",
            },
            {
                "label": "Mac VNC",
                "group": "Personal 2",
                "group_slug": "personal-2",
                "tone_group": "personal",
                "url": "remmina://castle",
                "lane": "make",
                "featured": True,
                "priority": 180,
                "note": "Mac fallback",
            },
            {
                "label": "Bridge State",
                "group": "Shared",
                "group_slug": "shared",
                "tone_group": "shared",
                "url": "/api/file?path=%2Fstate",
                "lane": "operate",
                "priority": 10,
            },
        ],
        {"norman"},
    )

    assert [lane["slug"] for lane in lanes] == ["make", "operate"]
    assert [item["label"] for item in lanes[0]["items"]] == ["Workbench", "Mac VNC"]
    assert lanes[0]["items"][1]["note"] == "Mac fallback"


def test_render_host_home_html_lists_public_tail_and_lan_console_links() -> None:
    module = _load_sync_agent_console_template()
    host = module.HOSTS["work-special"]
    instance = module.ConsoleInstance(
        name="control-plane",
        host_name="work-special",
        ssh_target=host.ssh_target,
        use_sudo=host.use_sudo,
        env_file="/etc/control-plane/codex-web.env",
        web_path="/usr/local/lib/control-plane/web.py",
        launch_path="/usr/local/lib/control-plane/launch.sh",
        supervisor_path="/usr/local/lib/control-plane/supervisor.sh",
        restart_units=(
            "control-plane-codex.service",
            "control-plane-codex-web.service",
        ),
        agent_label="Control Plane",
        web_port="8783",
        web_token="demo-token",
        prompt_file="/etc/control-plane/codex-system-prompt.txt",
        codex_home="/home/operator/.codex-control-plane",
    )

    rendered = module.render_host_home_html(host, [instance])

    assert "Work Special" in rendered
    assert "Control Plane" in rendered
    assert "cp.work.example.test" in rendered
    assert "work-special.home.arpa:8783" in rendered
    assert "work-special.tail00000.ts.net:8783" in rendered
    assert "192.168.0.147:8783" in rendered


def test_render_host_home_html_lists_named_home_arpa_override_links() -> None:
    module = _load_sync_agent_console_template()
    host = module.HOSTS["toy-box"]
    instance = module.ConsoleInstance(
        name="dj",
        host_name="toy-box",
        ssh_target=host.ssh_target,
        use_sudo=host.use_sudo,
        env_file="/etc/dj/codex-web.env",
        web_path="/opt/housebot/scripts/housebot_codex_web.py",
        launch_path="/opt/housebot/scripts/housebot_codex_launch.sh",
        supervisor_path="/opt/housebot/scripts/housebot_codex_supervisor.sh",
        restart_units=("dj-codex.service", "dj-codex-web.service"),
        agent_label="DJ Station",
        web_port="8793",
        web_token="demo-token",
        prompt_file="/etc/dj/codex-system-prompt.txt",
        codex_home="/root/.codex-dj",
    )

    rendered = module.render_host_home_html(host, [instance])

    assert "DJ Station" in rendered
    assert "https://dj.home.arpa/?token=demo-token" in rendered
    assert "toy-box.home.arpa:8793" in rendered
    assert "192.168.0.146:8793" in rendered


def test_toy_box_sync_uses_tailnet_ssh_without_changing_published_hosts() -> None:
    module = _load_sync_agent_console_template()

    host = module.HOSTS["toy-box"]

    assert host.ssh_target == "root@toy-box.tail00000.ts.net"
    assert host.public_host == "toy-box.home.arpa"
    assert host.lan_host == "192.168.0.146"
    assert "toy-box.tail00000.ts.net" in host.alias_hosts


def test_host_home_urls_use_norman_host_route() -> None:
    module = _load_sync_agent_console_template()

    urls = module.host_home_urls(module.HOSTS["norman"])

    assert ("norman.home.arpa", "http://norman.home.arpa/host/") in urls
    assert ("norman.tail00000.ts.net", "http://norman.tail00000.ts.net/host/") in urls


def test_bot_proxy_caddy_routes_forward_original_prefix() -> None:
    source = _bot_proxy_renderer_source()

    assert "header_up X-Forwarded-Prefix /bot/{slug}" in source


def test_bot_proxy_caddy_separates_public_work_hosts_from_internal_tls_hosts() -> None:
    source = _bot_proxy_renderer_source()

    assert "goldbook.work.example.test" in source
    assert "platinum.work.example.test" in source
    assert "keystone.work.example.test" in source
    assert "infra.work.example.test" in source
    assert "kpis.work.example.test" in source
    assert "dashboards.work.example.test" in source
    assert "mls.work.example.test" in source
    assert "scout.work.example.test" in source
    assert '"dj": ("dj", "yt")' in source
    assert '"studio": ("studio", "camera-studio")' in source
    assert '"tv": ("tv",)' in source
    assert "def bot_host_groups" in source
    assert 'host.endswith(".work.example.test")' in source
    assert "BOT_PUBLIC_INTERNAL_TLS_NAMES" in source


def test_bot_proxy_caddy_uses_internal_tls_for_pending_public_work_aliases(
    monkeypatch,
) -> None:
    module = _load_bot_proxy_renderer()
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered = module.render_hosts()

    assert "# compere" in rendered
    assert "keystone.work.example.test {\n    tls internal" in rendered
    assert "infra.work.example.test {\n    tls internal" in rendered
    assert (
        "kpis.work.example.test, leadership.work.example.test {\n    tls internal"
        in rendered
    )
    assert "scout.work.example.test {\n    tls internal" in rendered
    assert (
        "dashboards.work.example.test, tmi.work.example.test {\n    tls internal"
        in rendered
    )
    assert (
        "cp.work.example.test, control.work.example.test {\n    tls internal"
        not in rendered
    )
    assert "goldbook.work.example.test {\n    tls internal" not in rendered
    assert "platinum.work.example.test {\n    tls internal" not in rendered


def test_bot_proxy_caddy_ip_gates_knox_local_work_aliases(monkeypatch) -> None:
    module = _load_bot_proxy_renderer()
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered = module.render_hosts()

    assert (
        "@knox_allowed remote_ip 127.0.0.1/32 ::1/128 192.168.0.1/32 "
        "192.168.0.136/32 100.64.0.73/32 192.168.0.137/32 "
        "100.112.62.71/32 192.168.0.140/32 100.109.202.7/32 "
        "192.168.0.141/32" in rendered
    )
    assert 'respond "forbidden" 403' in rendered
    assert (
        "keystone.work.example.test {\n"
        "    tls internal\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "infra.work.example.test {\n" "    tls internal\n" "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "cp.work.example.test, control.work.example.test {\n"
        "    @knox_allowed remote_ip" not in rendered
    )
    assert "goldbook.work.example.test {\n    @knox_allowed remote_ip" not in rendered
    assert "platinum.work.example.test {\n    @knox_allowed remote_ip" not in rendered


def test_bot_proxy_dns_json_includes_static_public_work_hosts(monkeypatch) -> None:
    module = _load_bot_proxy_renderer()

    class Host:
        ssh_target = ""
        use_sudo = False

        def __init__(self, lan_host: str) -> None:
            self.lan_host = lan_host

    monkeypatch.setattr(
        module,
        "HOSTS",
        {
            "norman": Host("192.168.0.241"),
            "work-special": Host("192.168.0.147"),
        },
    )
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered_dns = module.render_dns_json()

    assert '"mc.work.example.test": "192.168.0.241"' in rendered_dns
    assert '"market.work.example.test": "192.168.0.241"' in rendered_dns
    assert '"mc.home.arpa": "192.168.0.241"' in rendered_dns
    assert '"market.home.arpa": "192.168.0.241"' in rendered_dns


def test_bot_proxy_dns_json_can_emit_tailnet_frontdoor_records(monkeypatch) -> None:
    module = _load_bot_proxy_renderer()

    class Host:
        ssh_target = ""
        use_sudo = False

        def __init__(self, lan_host: str) -> None:
            self.lan_host = lan_host

    class Instance:
        host_name = "toy-box"
        web_port = "8787"

    monkeypatch.setattr(
        module,
        "HOSTS",
        {
            "norman": Host("192.168.0.241"),
            "toy-box": Host("192.168.0.146"),
        },
    )
    monkeypatch.setattr(
        module,
        "discover_all_instances",
        lambda: ({}, {"housebot": Instance()}),
    )

    rendered_dns = module.render_dns_json("tailnet")

    assert '"housebot.home.arpa": "100.64.0.17"' in rendered_dns
    assert '"bbs.home.arpa": "100.64.0.17"' in rendered_dns
    assert '"switchboard.home.arpa": "100.64.0.17"' in rendered_dns


def test_bot_proxy_static_fallbacks_cover_active_home_and_shared_tuis(
    monkeypatch,
) -> None:
    module = _load_bot_proxy_renderer()

    class Host:
        ssh_target = ""
        use_sudo = False

        def __init__(self, lan_host: str) -> None:
            self.lan_host = lan_host

    monkeypatch.setattr(
        module,
        "HOSTS",
        {
            "norman": Host("192.168.0.241"),
            "toy-box": Host("192.168.0.146"),
            "hal": Host("192.168.0.137"),
            "private-host": Host("192.168.0.148"),
            "networking-host": Host("192.168.0.242"),
            "work-special": Host("192.168.0.147"),
        },
    )
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered_hosts = module.render_hosts()
    rendered_dns = module.render_dns_json("tailnet")

    assert "housebot.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.0.146:8787" in rendered_hosts
    assert "diamond-roc.home.arpa, diamondroc.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.0.146:8796" in rendered_hosts
    assert "eyebat.home.arpa, eyeball.home.arpa" in rendered_hosts
    assert "networking.home.arpa, netbot.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.0.242:8791" in rendered_hosts
    assert '"housebot.home.arpa": "100.64.0.17"' in rendered_dns
    assert '"diamond-roc.home.arpa": "100.64.0.17"' in rendered_dns
    assert '"networking.home.arpa": "100.64.0.17"' in rendered_dns
    assert rendered_hosts.count("mc.work.example.test") == 2


def test_bot_proxy_caddy_exposes_switchboard_with_legacy_aliases(monkeypatch) -> None:
    module = _load_bot_proxy_renderer()
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered_paths = module.render_paths()
    rendered_hosts = module.render_hosts()

    assert "# subprime" in rendered_paths
    assert "redir /bot/subprime /bot/subprime/ 308" in rendered_paths
    assert "# switchboard" in rendered_paths
    assert "redir /bot/switchboard /bot/switchboard/ 308" in rendered_paths
    assert "reverse_proxy 192.168.0.241:8796" in rendered_paths

    assert "# switchboard" in rendered_hosts
    assert "switchboard.home.arpa" in rendered_hosts
    assert "switchboard.norman.home.arpa" in rendered_hosts
    assert "subprime.home.arpa" in rendered_hosts
    assert "subprime.norman.home.arpa" in rendered_hosts
    assert "botprime.home.arpa" in rendered_hosts
    assert "bot.norman.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.0.241:8796" in rendered_hosts


def test_bot_proxy_caddy_exposes_bbs_on_norman_without_bot_path(monkeypatch) -> None:
    module = _load_bot_proxy_renderer()
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered_paths = module.render_paths()
    rendered_hosts = module.render_hosts()

    assert "# bbs" not in rendered_paths
    assert "/bot/bbs" not in rendered_paths
    assert "# bbs" in rendered_hosts
    assert "http://bbs.home.arpa" in rendered_hosts
    assert "bbs.home.arpa {\n    tls internal" in rendered_hosts
    assert "reverse_proxy 192.168.0.241:8765" in rendered_hosts


def test_bot_proxy_caddy_keeps_glimpser_service_and_bot_names_separate(
    monkeypatch,
) -> None:
    module = _load_bot_proxy_renderer()

    class Host:
        def __init__(self, lan_host: str) -> None:
            self.lan_host = lan_host

    class Instance:
        host_name = "toy-box"
        web_port = "8788"

    monkeypatch.setattr(
        module,
        "HOSTS",
        {
            "norman": Host("192.168.0.241"),
            "toy-box": Host("192.168.0.146"),
        },
    )
    monkeypatch.setattr(
        module,
        "discover_all_instances",
        lambda: ({}, {"glimpser": Instance()}),
    )

    rendered_hosts = module.render_hosts()
    rendered_dns = module.render_dns_json()

    assert module.bot_hosts("glimpser") == (
        "eyebat.home.arpa",
        "eyeball.home.arpa",
    )
    assert "eyebat.home.arpa" in rendered_hosts
    assert "eyeball.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.0.146:8788" in rendered_hosts
    assert '"eyebat.home.arpa": "192.168.0.241"' in rendered_dns
    assert '"eyeball.home.arpa": "192.168.0.241"' in rendered_dns
    assert "eyeballbot.home.arpa" not in rendered_hosts
    assert "glimpse.home.arpa" not in rendered_hosts
    assert "glimpserbot.home.arpa" not in rendered_hosts


def test_directory_shortcuts_prefer_public_work_bot_hosts() -> None:
    home_source = _home_js_source()
    systems_source = _systems_js_source()

    for source in (home_source, systems_source):
        assert "glimpser.home.arpa" in source
        assert "glimpse.home.arpa" not in source
        assert "dj.home.arpa" in source
        assert "tv.home.arpa" not in source
        assert "studio.home.arpa" not in source
        assert "null-agent" in source
        assert "goldbook.work.example.test" in source
        assert "platinum.work.example.test" in source
        assert "keystone.work.example.test" in source
        assert "infra.work.example.test" in source
        assert "kpis.work.example.test" in source
        assert "dashboards.work.example.test" in source
        assert "mls.work.example.test" in source
        assert "scout.work.example.test" in source
        assert "publisher.work.example.test" not in source


def test_directory_classifies_diamond_roc_as_toy_box_personal_service() -> None:
    home_source = _home_js_source()
    systems_source = _systems_js_source()

    for source in (home_source, systems_source):
        assert "'diamond-roc': 10" in source
        assert (
            "'toy-box-home', 'housebot', 'glimpser', 'dj', 'castle', "
            "'diamond-roc', 'phone-ops'"
        ) in source
        assert "'diamond-roc': 'diamond-roc.home.arpa'" in source
        assert "routeText.includes('toy box')" in source


def test_sync_template_prefers_public_work_console_url() -> None:
    module = _load_sync_agent_console_template()

    instance = module.ConsoleInstance(
        name="control-plane",
        host_name="work-special",
        ssh_target="root@192.168.0.147",
        use_sudo=False,
        env_file="/etc/control-plane/codex-web.env",
        web_path="/usr/local/lib/control-plane/web.py",
        launch_path="/usr/local/lib/control-plane/launch.sh",
        supervisor_path="/usr/local/lib/control-plane/supervisor.sh",
        restart_units=(
            "control-plane-codex.service",
            "control-plane-codex-web.service",
        ),
        agent_label="Control Plane",
        web_port="8783",
        web_token="demo-token",
        prompt_file="/etc/control-plane/codex-system-prompt.txt",
        codex_home="/home/operator/.codex-control-plane",
    )

    assert module.instance_public_host(instance) == "cp.work.example.test"
    urls = module.instance_console_urls(instance)
    assert urls["url"] == (
        "https://cp.work.example.test/?token=demo-token&profile={profile}"
    )
    assert urls["tail_url"] == (
        "http://work-special.tail00000.ts.net:8783/?token=demo-token&profile={profile}"
    )


def test_sync_template_prefers_phone_ops_console_route() -> None:
    module = _load_sync_agent_console_template()

    instance = module.ConsoleInstance(
        name="phone-ops",
        host_name="toy-box",
        ssh_target="root@toy-box.tail00000.ts.net",
        use_sudo=False,
        env_file="/etc/phone-ops/codex-web.env",
        web_path="/opt/phone-ops/codex-web.py",
        launch_path="/opt/phone-ops/codex-launch.sh",
        supervisor_path="/opt/phone-ops/codex-supervisor.sh",
        restart_units=("phone-ops-codex.service", "phone-ops-codex-web.service"),
        agent_label="Phone Ops",
        web_port="8790",
        web_token="demo-token",
        prompt_file="/etc/phone-ops/codex-system-prompt.txt",
        codex_home="/home/operator/.codex-phone-ops",
    )

    assert module.instance_console_urls(instance)["url"] == (
        "https://phone.home.arpa/?token=demo-token&profile={profile}"
    )


def test_sync_template_prefers_vanity_proxy_console_routes_for_home_tuis() -> None:
    module = _load_sync_agent_console_template()

    housebot = module.ConsoleInstance(
        name="housebot",
        host_name="toy-box",
        ssh_target="root@toy-box.tail00000.ts.net",
        use_sudo=False,
        env_file="/etc/housebot/codex-web.env",
        web_path="/opt/housebot/codex-web.py",
        launch_path="/opt/housebot/codex-launch.sh",
        supervisor_path="/opt/housebot/codex-supervisor.sh",
        restart_units=("housebot-codex.service", "housebot-codex-web.service"),
        agent_label="Housebot",
        web_port="8787",
        web_token="house-token",
        prompt_file="/etc/housebot/codex-system-prompt.txt",
        codex_home="/home/operator/.codex-housebot",
    )
    glimpser = module.ConsoleInstance(
        name="glimpser",
        host_name="toy-box",
        ssh_target="root@toy-box.tail00000.ts.net",
        use_sudo=False,
        env_file="/etc/glimpser/codex-web.env",
        web_path="/opt/glimpser/codex-web.py",
        launch_path="/opt/glimpser/codex-launch.sh",
        supervisor_path="/opt/glimpser/codex-supervisor.sh",
        restart_units=("glimpser-codex.service", "glimpser-codex-web.service"),
        agent_label="Glimpser",
        web_port="8788",
        web_token="eye-token",
        prompt_file="/etc/glimpser/codex-system-prompt.txt",
        codex_home="/home/operator/.codex-glimpser",
    )

    housebot_urls = module.instance_console_urls(housebot)
    glimpser_urls = module.instance_console_urls(glimpser)

    assert housebot_urls["url"] == (
        "https://housebot.home.arpa/?token=house-token&profile={profile}"
    )
    assert housebot_urls["tail_url"] == (
        "http://toy-box.tail00000.ts.net:8787/?token=house-token&profile={profile}"
    )
    assert glimpser_urls["url"] == (
        "https://eyebat.home.arpa/?token=eye-token&profile={profile}"
    )
    assert "eyebat.home.arpa:8788" not in glimpser_urls["url"]


def test_sync_template_promotes_phone_ops_into_fold_links() -> None:
    module = _load_sync_agent_console_template()

    switchboard = module.ConsoleInstance(
        name="switchboard",
        host_name="norman",
        ssh_target="root@192.168.0.241",
        use_sudo=False,
        env_file="/etc/norman/norman-bot-prime-codex.env",
        web_path="/home/operator/code/norman/scripts/norman_codex_web.py",
        launch_path="/home/operator/code/norman/scripts/norman_codex_launch.sh",
        supervisor_path="/home/operator/code/norman/scripts/norman_codex_supervisor.sh",
        restart_units=(
            "norman-bot-prime-codex.service",
            "norman-bot-prime-codex-web.service",
        ),
        agent_label="Switchboard",
        web_port="8796",
        web_token="switchboard-token",
        prompt_file="/home/operator/code/norman/scripts/norman_subprime_prompt.txt",
        codex_home="/home/operator/.codex-bot-prime",
    )
    phone_ops = module.ConsoleInstance(
        name="phone-ops",
        host_name="toy-box",
        ssh_target="root@toy-box.tail00000.ts.net",
        use_sudo=False,
        env_file="/etc/phone-ops/codex-web.env",
        web_path="/opt/phone-ops/codex-web.py",
        launch_path="/opt/phone-ops/codex-launch.sh",
        supervisor_path="/opt/phone-ops/codex-supervisor.sh",
        restart_units=("phone-ops-codex.service", "phone-ops-codex-web.service"),
        agent_label="Phone Ops",
        web_port="8790",
        web_token="phone-token",
        prompt_file="/etc/phone-ops/codex-system-prompt.txt",
        codex_home="/home/operator/.codex-phone-ops",
    )

    links = module.desired_console_links(
        switchboard,
        discovered_by_host={"norman": [switchboard], "toy-box": [phone_ops]},
        discovered_by_name={"switchboard": switchboard, "phone-ops": phone_ops},
    )

    phone_link = next(item for item in links if item["label"] == "Phone Ops")
    assert phone_link["featured"] is True
    assert phone_link["group"] == "Personal"
    assert phone_link["url"] == (
        "https://phone.home.arpa/?token=phone-token&profile={profile}"
    )


def test_sync_template_ignores_diamond_roc_discovered_on_hal(monkeypatch) -> None:
    module = _load_sync_agent_console_template()

    def instance(name: str, host_name: str):
        host = module.HOSTS[host_name]
        return module.ConsoleInstance(
            name=name,
            host_name=host_name,
            ssh_target=host.ssh_target,
            use_sudo=host.use_sudo,
            env_file=f"/etc/{name}/codex-web.env",
            web_path=f"/opt/{name}/codex-web.py",
            launch_path=f"/opt/{name}/codex-launch.sh",
            supervisor_path=f"/opt/{name}/codex-supervisor.sh",
            restart_units=(f"{name}-codex.service", f"{name}-codex-web.service"),
            agent_label="Diamond Roc",
            web_port="8797",
            web_token="demo-token",
            prompt_file=f"/etc/{name}/codex-system-prompt.txt",
            codex_home=f"/home/operator/.codex-{name}",
        )

    stale_hal = instance("diamond-roc", "hal")
    toy_box = instance("diamond-roc", "toy-box")
    discovered = {"hal": [stale_hal], "toy-box": [toy_box]}

    monkeypatch.setattr(
        module,
        "discover_host_instances",
        lambda host: discovered.get(host.name, []),
    )

    by_host, by_name = module.discover_all_instances()

    assert by_host["hal"] == []
    assert by_host["toy-box"] == [toy_box]
    assert by_name["diamond-roc"].host_name == "toy-box"


def test_sync_template_uses_new_work_alias_canonicals() -> None:
    module = _load_sync_agent_console_template()

    for name, expected in (
        ("compere", "keystone.work.example.test"),
        ("infra", "infra.work.example.test"),
        ("leadership-kpis", "kpis.work.example.test"),
        ("scout", "scout.work.example.test"),
        ("tmi-dashboards", "dashboards.work.example.test"),
    ):
        instance = module.ConsoleInstance(
            name=name,
            host_name="work-special",
            ssh_target="root@192.168.0.147",
            use_sudo=False,
            env_file=f"/etc/{name}/codex-web.env",
            web_path=f"/usr/local/lib/{name}/web.py",
            launch_path=f"/usr/local/lib/{name}/launch.sh",
            supervisor_path=f"/usr/local/lib/{name}/supervisor.sh",
            restart_units=(f"{name}-codex.service", f"{name}-codex-web.service"),
            agent_label=name.title(),
            web_port="8780",
            web_token="demo-token",
            prompt_file=f"/etc/{name}/codex-system-prompt.txt",
            codex_home=f"/home/operator/.codex-{name}",
        )
        assert module.instance_public_host(instance) == expected


def test_sync_template_archives_publisher_tui() -> None:
    module = _load_sync_agent_console_template()

    assert "publisher" in module.ARCHIVED_INSTANCE_NAMES


def test_sync_template_treats_hal_as_root_managed_local_host() -> None:
    module = _load_sync_agent_console_template()

    hal = module.HOSTS["hal"]

    assert hal.local is True
    assert hal.read_only is False
    assert hal.root_managed_local is True


def test_sync_template_source_skips_root_managed_local_host_in_user_sync() -> None:
    source = _sync_agent_console_template_source()

    assert (
        "root-managed local host; skipping local template/env writes in user sync"
        in source
    )


def test_local_sync_systemd_units_target_hal() -> None:
    service = _systemd_unit_source("norman-agent-console-sync-local.service")
    path = _systemd_unit_source("norman-agent-console-sync-local.path")
    timer = _systemd_unit_source("norman-agent-console-sync-local.timer")

    assert "sync_agent_console_template.py --targets hal" in service
    assert (
        "/home/operator/code/norman/scripts/agent_console_template/agent_console_web.py"
        in path
    )
    assert "Unit=norman-agent-console-sync-local.service" in path
    assert "Unit=norman-agent-console-sync-local.service" in timer


def test_requested_host_filter_only_short_circuits_when_targets_are_hosts() -> None:
    module = _load_sync_agent_console_template()

    assert module.requested_host_filter(["hal", "norman"]) == ["hal", "norman"]
    assert module.requested_host_filter(["hal", "hal", "norman"]) == [
        "hal",
        "norman",
    ]
    assert module.requested_host_filter(["hal", "autocamera"]) is None


def test_canonical_origin_uses_https_for_public_work_hosts() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "cp.work.example.test"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "cp.work.example.test,work-special.home.arpa,192.168.0.147"
        )
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = old_aliases

    assert module.canonical_origin_components() == (
        "https",
        "cp.work.example.test",
    )


def test_canonical_origin_uses_http_for_home_arpa_hosts() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "work-special.home.arpa"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "work-special.home.arpa,192.168.0.147"
        )
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = old_aliases

    assert module.canonical_origin_components() == (
        "http",
        f"work-special.home.arpa:{module.PORT}",
    )


def test_should_redirect_canonical_without_query_token_for_public_work_host() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    old_token = os.environ.get("HOUSEBOT_CODEX_WEB_TOKEN")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "cp.work.example.test"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "work-special.home.arpa,192.168.0.147"
        )
        os.environ["HOUSEBOT_CODEX_WEB_TOKEN"] = "demo-token"
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = old_aliases
        if old_token is None:
            os.environ.pop("HOUSEBOT_CODEX_WEB_TOKEN", None)
        else:
            os.environ["HOUSEBOT_CODEX_WEB_TOKEN"] = old_token

    handler = object.__new__(module.Handler)
    handler.headers = {"Host": "work-special.home.arpa:8783"}
    handler.client_address = ("192.168.0.50", 12345)

    parsed = module.urlparse("http://work-special.home.arpa:8783/?profile=slate")

    assert module.Handler.should_redirect_canonical(
        handler,
        parsed,
        {"profile": ["slate"]},
    )


def test_render_console_link_url_keeps_sibling_service_hostnames() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    old_port = os.environ.get("HOUSEBOT_CODEX_WEB_PORT")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "dj.home.arpa"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "dj.home.arpa,toy-box.home.arpa,192.168.0.146"
        )
        os.environ["HOUSEBOT_CODEX_WEB_PORT"] = "8793"
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = old_aliases
        if old_port is None:
            os.environ.pop("HOUSEBOT_CODEX_WEB_PORT", None)
        else:
            os.environ["HOUSEBOT_CODEX_WEB_PORT"] = old_port

    same_service = module.render_console_link_url(
        {
            "url": "http://toy-box.home.arpa:8793/?token={token}&profile={profile}",
            "lan_url": "http://192.168.0.146:8793/?token={token}&profile={profile}",
        },
        token="demo-token",
        profile="slate",
        request_host="dj.home.arpa",
        route_mode="host",
    )
    sibling_service = module.render_console_link_url(
        {
            "url": "http://toy-box.home.arpa:8787/?token={token}&profile={profile}",
            "lan_url": "http://192.168.0.146:8787/?token={token}&profile={profile}",
        },
        token="demo-token",
        profile="slate",
        request_host="dj.home.arpa",
        route_mode="host",
    )

    assert same_service.startswith("http://dj.home.arpa:8793/")
    assert sibling_service.startswith("http://toy-box.home.arpa:8787/")


def test_render_console_link_url_falls_back_to_tail_when_remote_from_lan_only_host() -> (
    None
):
    module = _load_agent_console_web()
    link = {
        "url": "http://toy-box.home.arpa:8793/?token={token}&profile={profile}",
        "lan_url": "http://192.168.0.146:8793/?token={token}&profile={profile}",
        "tail_url": "http://toy-box.tail00000.ts.net:8793/?token={token}&profile={profile}",
    }

    remote_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="cp.work.example.test",
        route_mode="auto",
    )
    lan_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="norman.home.arpa",
        route_mode="auto",
    )
    stale_lan_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="cp.work.example.test",
        route_mode="lan",
    )

    assert remote_rendered == (
        "http://toy-box.tail00000.ts.net:8793/?token=demo-token&profile=slate"
    )
    assert lan_rendered == "http://192.168.0.146:8793/?token=demo-token&profile=slate"
    assert stale_lan_rendered.startswith("http://toy-box.tail00000.ts.net:8793/")
    assert "route=lan" in stale_lan_rendered


def test_render_console_link_url_prefers_tail_for_tailnet_client_on_home_arpa() -> None:
    module = _load_agent_console_web()
    link = {
        "url": "https://housebot.home.arpa/?token={token}&profile={profile}",
        "lan_url": "http://192.168.0.146:8787/?token={token}&profile={profile}",
        "tail_url": "http://toy-box.tail00000.ts.net:8787/?token={token}&profile={profile}",
    }

    tailnet_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="norman.home.arpa",
        route_mode="auto",
        client_ip="100.64.0.73",
    )
    lan_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="norman.home.arpa",
        route_mode="auto",
        client_ip="192.168.0.136",
    )

    assert tailnet_rendered == (
        "http://toy-box.tail00000.ts.net:8787/?token=demo-token&profile=slate"
    )
    assert lan_rendered == "http://192.168.0.146:8787/?token=demo-token&profile=slate"


def test_render_console_link_url_supports_explicit_tail_route() -> None:
    module = _load_agent_console_web()

    rendered = module.render_console_link_url(
        {
            "url": "https://cp.work.example.test/?token={token}&profile={profile}",
            "lan_url": "http://192.168.0.147:8783/?token={token}&profile={profile}",
            "tail_url": "http://work-special.tail00000.ts.net:8783/?token={token}&profile={profile}",
        },
        token="demo-token",
        profile="slate",
        request_host="work-special.home.arpa",
        route_mode="tail",
    )

    assert rendered.startswith("http://work-special.tail00000.ts.net:8783/")
    assert "token=demo-token" in rendered
    assert "profile=slate" in rendered
    assert "route=tail" in rendered
