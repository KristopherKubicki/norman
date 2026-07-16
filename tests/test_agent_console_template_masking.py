from __future__ import annotations

import io
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_agent_console_test_temp_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove every temporary directory this legacy integration module creates."""
    created_dirs: list[Path] = []
    original_mkdtemp = tempfile.mkdtemp

    def tracked_mkdtemp(*args, **kwargs) -> str:
        directory = Path(original_mkdtemp(*args, **kwargs))
        created_dirs.append(directory)
        return str(directory)

    monkeypatch.setattr(tempfile, "mkdtemp", tracked_mkdtemp)
    yield

    for directory in reversed(created_dirs):
        shutil.rmtree(directory, ignore_errors=True)
    leftovers = [str(directory) for directory in created_dirs if directory.exists()]
    assert not leftovers, f"test temporary directories were not removed: {leftovers}"


def _load_agent_console_web():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_web.py"
    )
    env_prefixes = ("NORMAN_CODEX_", "HOUSEBOT_CODEX_")
    env_snapshot = {
        key: value for key, value in os.environ.items() if key.startswith(env_prefixes)
    }
    if "NORMAN_CODEX_WEB_STATE_DIR" not in os.environ:
        os.environ["NORMAN_CODEX_WEB_STATE_DIR"] = tempfile.mkdtemp(
            prefix="norman-agent-console-test-"
        )
    for key, value in list(os.environ.items()):
        if key.startswith("HOUSEBOT_CODEX_"):
            suffix = key.removeprefix("HOUSEBOT_CODEX_")
            os.environ[f"NORMAN_CODEX_{suffix}"] = value
    spec = importlib.util.spec_from_file_location("agent_console_web", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for key in list(os.environ):
            if key.startswith(env_prefixes) and key not in env_snapshot:
                os.environ.pop(key, None)
        for key, value in env_snapshot.items():
            os.environ[key] = value
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


def _agent_console_supervisor_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_supervisor.sh"
    ).read_text(encoding="utf-8")


def test_agent_console_templates_default_to_gpt_55() -> None:
    launch_source = _agent_console_launch_source()

    assert 'MODEL="${HOUSEBOT_CODEX_MODEL:-gpt-5.5}"' in launch_source
    assert 'CODEX_BIN="${HOUSEBOT_CODEX_BIN:-}"' in launch_source
    assert "/opt/node-v20.19.6/bin/codex" in launch_source
    assert "/home/kristopher/.nvm/versions/node/v20.19.6/bin/codex" in launch_source
    assert '"$CODEX_BIN" \\' in launch_source
    assert (
        'MODEL = os.environ.get("HOUSEBOT_CODEX_MODEL", "gpt-5.5")'
        in _agent_console_web_source()
    )


def test_agent_console_promotes_stale_codex_model_setting_to_floor() -> None:
    module = _load_agent_console_web()
    module.RUNTIME_SETTINGS_PATH.write_text(
        json.dumps(
            {
                "runtime": "codex",
                "model": "openai.gpt-5.4",
                "service_tier": "default",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    expected_model = module.MODEL

    assert module.codex_model_below_floor("openai.gpt-5.4") is True
    assert module.normalize_runtime_model("codex", "openai.gpt-5.4") == expected_model
    assert module.configured_chat_model() == expected_model
    assert module.configured_runtime_model("codex") == expected_model

    settings = module.save_runtime_settings(
        {"runtime": "codex", "model": "openai.gpt-5.4", "service_tier": "default"}
    )

    assert settings["model"] == expected_model
    assert settings["model"] != "openai.gpt-5.4"
    assert all(
        item["key"] not in {"codex-openai-5-4", "codex-bedrock-5-4"}
        for item in module.model_route_presets_payload()
    )


def test_agent_console_can_explicitly_enable_legacy_codex_compat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NORMAN_CODEX_ALLOW_BELOW_FLOOR_SWITCHABLE", "1")
    module = _load_agent_console_web()

    assert module.normalize_runtime_model("codex", "openai.gpt-5.4") == "openai.gpt-5.4"
    assert any(
        item["key"] == "codex-bedrock-5-4"
        for item in module.model_route_presets_payload()
    )


def test_route_receipt_default_path_uses_tui_state_dir() -> None:
    source = _agent_console_web_source()

    assert 'str(STATE_DIR / "route_receipts")' in source
    assert '"/var/lib/norman/route_receipts"' not in source


def test_route_receipt_write_permission_failure_is_nonfatal(tmp_path) -> None:
    module = _load_agent_console_web()
    blocked_dir = tmp_path / "blocked"
    blocked_dir.mkdir()
    blocked_dir.chmod(0o500)
    old_enabled = module.ROUTE_RECEIPTS_ENABLED
    old_path = module.ROUTE_RECEIPT_PATH
    old_error = module.ROUTE_RECEIPT_LAST_WRITE_ERROR
    try:
        module.ROUTE_RECEIPTS_ENABLED = True
        module.ROUTE_RECEIPT_PATH = blocked_dir / "norman.jsonl"
        module.ROUTE_RECEIPT_LAST_WRITE_ERROR = ""

        receipt = module.append_route_receipt(
            prompt="status?",
            visible_response="ready",
            error_text="",
            started_at=1712878300,
            finished_at=1712878302,
            thread_id="thread-test",
            speed="normal",
            detail=2,
            service_tier="default",
            job_budget="normal",
            optimization_mode="optimized",
            success=True,
            runtime="codex",
            model="gpt-5.5",
            usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
        snapshot = module.route_receipt_status_snapshot()
    finally:
        module.ROUTE_RECEIPTS_ENABLED = old_enabled
        module.ROUTE_RECEIPT_PATH = old_path
        module.ROUTE_RECEIPT_LAST_WRITE_ERROR = old_error
        blocked_dir.chmod(0o700)

    assert receipt is not None
    assert receipt["mirror_status"] == "write_failed"
    assert "Permission denied" in receipt["mirror_error"]
    assert snapshot["status"] == "degraded"
    assert "Permission denied" in snapshot["last_write_error"]


def test_empty_route_receipt_mirror_is_not_failed(tmp_path) -> None:
    module = _load_agent_console_web()
    receipt_path = tmp_path / "route_receipts" / "norman.jsonl"
    receipt_path.parent.mkdir()
    receipt_path.touch()

    snapshot = module.route_receipt_chain_status(receipt_path)

    assert snapshot["status"] == "empty"
    assert snapshot["receipt_count"] == 0
    assert snapshot["issue_count"] == 0
    assert snapshot["issues"] == []


def test_route_receipt_status_prefers_state_db_over_jsonl(tmp_path) -> None:
    module = _load_agent_console_web()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    receipt_path = state_dir / "route_receipts" / "norman.jsonl"
    old_enabled = module.ROUTE_RECEIPTS_ENABLED
    old_path = module.ROUTE_RECEIPT_PATH
    old_lock_path = module.ROUTE_RECEIPT_LOCK_PATH
    old_db_path = module.STATE_DB_PATH
    old_state_db_enabled = module.STATE_DB_ENABLED
    old_error = module.ROUTE_RECEIPT_LAST_WRITE_ERROR
    try:
        module.ROUTE_RECEIPTS_ENABLED = True
        module.STATE_DB_ENABLED = True
        module.ROUTE_RECEIPT_PATH = receipt_path
        module.ROUTE_RECEIPT_LOCK_PATH = receipt_path.with_name(
            f"{receipt_path.name}.lock"
        )
        module.STATE_DB_PATH = state_dir / "tui_state.sqlite3"
        module.ROUTE_RECEIPT_LAST_WRITE_ERROR = ""

        receipt = module.append_route_receipt(
            prompt="status?",
            visible_response="ready",
            error_text="",
            started_at=1712878300,
            finished_at=1712878302,
            thread_id="thread-test",
            speed="normal",
            detail=2,
            service_tier="default",
            job_budget="normal",
            optimization_mode="optimized",
            success=True,
            runtime="codex",
            model="gpt-5.5",
            usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
        receipt_path.write_text("{not-json}\n", encoding="utf-8")

        snapshot = module.route_receipt_status_snapshot()
    finally:
        module.ROUTE_RECEIPTS_ENABLED = old_enabled
        module.ROUTE_RECEIPT_PATH = old_path
        module.ROUTE_RECEIPT_LOCK_PATH = old_lock_path
        module.STATE_DB_PATH = old_db_path
        module.STATE_DB_ENABLED = old_state_db_enabled
        module.ROUTE_RECEIPT_LAST_WRITE_ERROR = old_error

    assert receipt is not None
    assert snapshot["status"] == "pass"
    assert snapshot["storage_source"] == "state_db"
    assert snapshot["receipt_count"] == 1
    assert snapshot["latest_hash"] == receipt["receipt_hash"]
    assert snapshot["issue_count"] == 0


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
    handler.client_address = ("192.168.2.241", 443)
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
    fixture_hosts = {
        "autocamera": "toy-box",
        "compere": "work-special",
        "control-plane": "work-special",
        "gold-book": "work-special",
        "housebot": "toy-box",
        "infra": "work-special",
        "leadership-kpis": "work-special",
        "market-sizing": "work-special",
        "mls": "work-special",
        "panelbot": "work-special",
        "platinum-standard": "work-special",
        "publisher": "work-special",
        "scout": "work-special",
        "theseus": "private-host",
        "tmi-dashboards": "work-special",
    }
    by_name = {
        name: SimpleNamespace(name=name, host_name=host_name, web_port=str(8780 + idx))
        for idx, (name, host_name) in enumerate(sorted(fixture_hosts.items()))
    }
    module.discover_all_instances = lambda: (list(by_name.values()), by_name)
    return module


def _load_frontdoor_renderer():
    _load_sync_agent_console_template()
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "render_norman_frontdoor_caddy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "render_norman_frontdoor_caddy", script_path
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

    assert "const INLINE_FILE_TARGET_LIMIT = 6;" in source
    assert "const INLINE_FILE_TARGET_SCAN_CHARS = 24000;" in source
    assert "const INLINE_IMAGE_GALLERY_LIMIT = 6;" in source
    assert "const INLINE_PREVIEW_VISIBLE_MESSAGE_LIMIT = 2;" in source
    assert "const INLINE_TEXT_PREVIEW_MAX_CHARS = 24000;" in source
    assert "const INLINE_TEXT_PREVIEW_RANGE_BYTES = 32768;" in source
    assert "const INLINE_PREVIEW_TIMEOUT_MS = 4500;" in source
    assert "const INLINE_PREVIEW_CACHE_LIMIT = 24;" in source
    assert (
        "function extractInlineFileTargets(value, limit = INLINE_FILE_TARGET_LIMIT)"
        in source
    )
    assert "if (results.length >= maxTargets) {{" in source
    assert "function buildFileDownloadHref(value) {" in source
    assert "function compactInlineFilePath(value) {" in source
    assert r"text.matchAll(/\[([^\]]+)\]\s*\(\s*(<[^>\\n]+>|[^\s)]+)\s*\)/g)" in source
    assert "function rememberInlineFilePreview(cacheKey, payload)" in source
    assert "function loadInlineFilePreview(entry)" in source
    assert (
        "window.setTimeout(() => controller.abort(), INLINE_PREVIEW_TIMEOUT_MS)"
        in source
    )
    assert "Range: `bytes=0-${{INLINE_TEXT_PREVIEW_RANGE_BYTES - 1}}`" in source
    assert (
        "const truncated = normalized.length > INLINE_TEXT_PREVIEW_MAX_CHARS" in source
    )
    assert "const visibleLines = lines.slice(0, 8);" in source
    assert "const totalMatch = contentRange.match(/\\/(\\d+)$/);" in source
    assert 'const lines = normalized.split("\\\\n");' in source
    assert "function buildInlineImagePreviewTile(entry)" in source
    assert "function renderInlineImagePreviewGallery(items)" in source
    assert "function renderInlineFilePreviews(container, targets)" in source
    assert ".message-file-previews {" in source
    assert "grid-template-columns: minmax(0, 1fr);" in source
    assert ".message-file-preview-gallery {" in source
    assert "grid-template-columns: repeat(6, minmax(0, 1fr));" in source
    assert ".inline-image-preview-tile {" in source
    assert ".inline-image-preview-caption {" in source
    assert ".inline-file-preview-summary {" in source
    assert ".inline-file-preview .inline-action {" in source
    assert "justify-content: space-between;" in source
    assert 'toggle.textContent = "View";' in source
    assert "subtle.textContent = compactInlineFilePath(entry.path);" in source
    assert 'download.textContent = "Save";' in source
    assert 'copy.textContent = "Path";' in source
    assert "body.hidden = true;" in source
    assert "if (imageEntries.length < 2) {{" in source
    assert (
        "const visible = imageEntries.slice(0, INLINE_IMAGE_GALLERY_LIMIT);" in source
    )
    assert "async function ensureLoaded() {" in source
    assert "async function setExpanded(nextExpanded) {" in source
    assert ".inline-file-preview-body img {" in source
    assert 'pre.className = "inline-file-preview-text";' in source
    assert 'previews.className = "message-file-previews";' in source
    assert "const shouldScanInlinePreviews = options.inlinePreviews !== false" in source
    assert (
        "const previewLimit = Math.max(0, Number(options.inlinePreviewLimit || INLINE_FILE_TARGET_LIMIT));"
        in source
    )
    assert "extractInlineFileTargets(body, previewLimit)" in source
    assert "inlinePreviews: allowInlinePreviews" in source
    assert "renderInlineFilePreviews(previews, previewTargets);" in source


def test_chat_renderer_lazily_collapses_heavy_messages() -> None:
    source = _agent_console_web_source()

    assert "const LARGE_REPLY_COLLAPSE_MIN_CHARS = 16000;" in source
    assert "const LARGE_REPLY_COLLAPSE_MIN_LINES = 120;" in source
    assert (
        "const largeReply = stats.lineCount >= LARGE_REPLY_COLLAPSE_MIN_LINES" in source
    )
    assert 'badge: cleanRole.includes("error") ? "Error" : "Reply",' in source
    assert '<div class="collapsed-prompt-body" hidden></div>' in source
    assert "let detailRendered = false;" in source
    assert 'detail.innerHTML = cleanRole.includes("error")' in source
    assert "if (opening) {{" in source
    assert "renderCollapsedDetail();" in source
    assert "return normalizeCopiedText(fallback);" in source


def test_file_raw_endpoint_supports_byte_ranges_for_lightweight_previews() -> None:
    source = _agent_console_web_source()

    assert 'range_header = self.headers.get("Range", "").strip()' in source
    assert 're.fullmatch(r"bytes=(\\d*)-(\\d*)", range_header)' in source
    assert "HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE" in source
    assert 'self.send_header("Accept-Ranges", "bytes")' in source
    assert (
        'self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")'
        in source
    )
    assert "handle.seek(start)" in source
    assert "handle.read(min(64 * 1024, remaining))" in source


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

    assert '"192.168.2.136",  # pixel10' in source
    assert '"100.78.41.73",  # pixel10 tailnet' in source
    assert '"100.112.62.71",  # hal tailnet' in source
    assert '"100.109.202.7",  # plasma-mobile tailnet' in source
    assert source.count('"192.168.2.136",  # pixel10') >= 2
    assert source.count('"100.78.41.73",  # pixel10 tailnet') >= 2


def test_prompt_input_rerouted_plain_text_paste_inserts_into_composer() -> None:
    source = _agent_console_web_source()

    assert "function insertTextIntoPrompt(text, options = {{}})" in source
    assert (
        "const reroutedPaste = Boolean(event && event.target && event.target !== el.promptInput);"
        in source
    )
    assert "insertTextIntoPrompt(pastedText, {{ placeAtEnd: true }});" in source


def test_large_user_paste_turns_collapse_into_summary_rails() -> None:
    source = _agent_console_web_source()

    assert "function promptBodyStats(value) {{" in source
    assert "function collapsedPromptDescriptor(role, body, options = {{}}) {{" in source
    assert 'class="collapsed-prompt-toggle"' in source
    assert 'badge: "Paste",' in source
    assert (
        '<span class="collapsed-prompt-badge">${{escapeHtml(collapsedPrompt.badge || "Text")}}</span>'
        in source
    )
    assert 'class="collapsed-prompt-body" hidden' in source


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


def test_template_exposes_norllama_tool_lane_activity() -> None:
    source = _agent_console_web_source()

    assert "norman.norllama.tool-activity.v1" in source
    assert 'if parsed.path == "/api/llm/tool-activity":' in source
    assert "function toolLaneState(snapshot) {{" in source
    assert 'label: "Tool lanes"' in source
    assert "latestToolCall" in source
    assert "route_guardrails" in source
    assert "laneGuardrails" in source
    assert '"/v1/safety/classify": "safety"' in source
    assert '"prompt_injection"' in source
    assert '"streaming_safety"' in source
    assert "lanes ready" in source


def test_template_exposes_route_utilization_metrics() -> None:
    source = _agent_console_web_source()

    assert "norman.tui.route-utilization.v1" in source
    assert '"route_utilization": route_utilization_snapshot(' in source
    assert "function routeUtilizationState(snapshot) {{" in source
    assert "const routeUtilization = routeUtilizationState(snapshot);" in source
    assert 'label: "Local share"' in source
    assert 'label: "Cloud avoided"' in source


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
    assert 'popup = window.open("", "_blank", "noopener,noreferrer");' in source
    assert "popup.location.replace(launchHref);" in source


def test_browser_signin_skips_blank_popup_when_lane_is_already_ready() -> None:
    source = _agent_console_web_source()

    assert 'if (!auth.required && snapshotState === "ok") {{' in source
    assert 'el.statusMessage.textContent = "Already signed in.";' in source
    assert "const bridgeAllowed = Boolean(BROWSER_AUTH_BRIDGE_ALLOWED);" in source
    assert "el.authBrowserButton.disabled = !required;" in source
    assert "el.authDeviceButton.disabled = !required;" in source
    assert (
        'el.authHelperLink.hidden = !required || mode !== "browser_signin";' in source
    )
    assert '? "Already signed in."' in source
    assert (
        "el.statusMessage.textContent = auth.required\n"
        '              ? "Browser sign-in was prepared, but no auth URL was returned. Refresh and retry."\n'
        '              : "No browser sign-in was needed.";' in source
    )


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


def test_start_browser_auth_reports_busy_local_callback_port() -> None:
    module = _load_agent_console_web()

    module.ensure_session = lambda: True
    module.current_snapshot = lambda: {
        "state": "error",
        "auth": {
            "required": True,
            "mode": "signin_choice",
            "summary": "Choose sign-in.",
            "verification_url": "",
            "device_code": "",
        },
    }
    module.capture_pane = lambda: (
        "Welcome to Codex, OpenAI's command-line coding agent\n\n"
        "Sign in with ChatGPT to use Codex as part of your paid plan\n"
        "or connect an API key for usage-based billing\n\n"
        "> 1. Sign in with ChatGPT\n"
        "  2. Sign in with Device Code\n"
        "  3. Provide your own API key\n\n"
        "Press Enter to continue\n"
    )
    module.read_text = lambda path, default="": ""
    module.run = lambda *args, **kwargs: None
    module._wait_for_pane = lambda predicate, timeout=0.0: (
        "Welcome to Codex, OpenAI's command-line coding agent\n"
        "Port 127.0.0.1:1455 is already in use\n"
    )

    with pytest.raises(RuntimeError, match="browser callback port"):
        module.start_browser_auth()


def test_start_browser_auth_is_noop_when_snapshot_is_already_ready() -> None:
    module = _load_agent_console_web()

    ready_snapshot = {
        "state": "ok",
        "status_message": "Ready.",
        "auth": {
            "required": False,
            "mode": "",
            "summary": "",
            "verification_url": "",
            "device_code": "",
        },
    }

    module.ensure_session = lambda: True
    module.current_snapshot = lambda: ready_snapshot
    module.capture_pane = lambda: (_ for _ in ()).throw(
        AssertionError("capture_pane should not run when the snapshot is already ready")
    )

    assert module.start_browser_auth() == ready_snapshot


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
        module.update_status_meta = lambda **updates: updates

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
        module.update_status_meta = lambda **updates: updates

        snapshot = module.current_snapshot()

        assert snapshot["auth"]["required"] is False
        assert snapshot["state"] == "ok"
        assert snapshot["status_message"] == "Ready."


def test_current_snapshot_ready_prompt_overrides_stale_error_meta_with_mcp_auth_noise() -> (
    None
):
    module = _load_agent_console_web()

    with tempfile.TemporaryDirectory() as temp_dir:
        last_error_path = Path(temp_dir) / "last_error.txt"
        last_error_path.write_text("", encoding="utf-8")
        status_path = Path(temp_dir) / "status.json"
        module.LAST_ERROR_PATH = last_error_path
        module.STATUS_PATH = status_path
        module.recover_stale_prompt_state = lambda: None
        module.load_status_meta = lambda: {
            **module.default_status_meta(),
            "state": "error",
            "status_message": "Restarted the interactive Norman Subprime Codex tmux session.",
            "pending": False,
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
        module.capture_pane = lambda: (
            "⚠ MCP client for `codex_apps` failed to start: token_expired\n"
            "■ Your access token could not be refreshed because your refresh token was already used. "
            "Please log out and sign in again.\n\n"
            "› Find and fix a bug in @filename\n\n"
            "  gpt-5.4 xhigh fast · 100% left · /home/kristopher/code/norman\n"
        )
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: True
        module.update_status_meta = lambda **updates: updates

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
        module.update_status_meta = lambda **updates: updates

        snapshot = module.current_snapshot()

        assert snapshot["state"] == "ok"
        assert snapshot["auth"]["required"] is False
        assert snapshot["last_error"] == ""
        assert last_error_path.read_text(encoding="utf-8") == ""


def test_current_snapshot_clears_stale_auth_error_at_signin_prompt() -> None:
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
        module.capture_pane = lambda: (
            "Welcome to Codex, OpenAI's command-line coding agent\n\n"
            "Sign in with ChatGPT to use Codex as part of your paid plan\n"
            "or connect an API key for usage-based billing\n\n"
            "> 1. Sign in with ChatGPT\n"
            "  2. Sign in with Device Code\n"
            "  3. Provide your own API key\n\n"
            "Press Enter to continue\n"
        )
        module.service_status = lambda names: [(name, "active") for name in names]
        module.usage_snapshot = lambda thread_id="": {
            "totals": {},
            "current_thread": {},
        }
        module.normalize_queue = lambda value: []
        module.load_draft_attachments = lambda: []
        module.prompt_thread_alive = lambda: False
        module.update_status_meta = lambda **updates: updates

        snapshot = module.current_snapshot()

        assert snapshot["auth"]["required"] is True
        assert snapshot["auth"]["mode"] == "signin_choice"
        assert snapshot["status_message"] == "Choose sign-in."
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


def test_initial_conversation_hides_placeholder_response_when_error_is_live() -> None:
    module = _load_agent_console_web()

    snapshot = {
        "history": [
            {
                "prompt": "status?",
                "response": "[no response returned]",
                "error": (
                    "unexpected status 401 Unauthorized: Missing bearer basic "
                    "authentication in header, url: "
                    "https://api.openai.com/v1/responses"
                ),
                "started_at": 0,
                "finished_at": 0,
                "speed": "balanced",
                "detail": 3,
            }
        ],
        "pending": False,
        "pane": "",
        "auth": {"required": False, "mode": "", "summary": ""},
        "state": "error",
        "last_error": (
            "unexpected status 401 Unauthorized: Missing bearer basic "
            "authentication in header"
        ),
    }

    rendered = module._initial_conversation_html(snapshot)

    assert "[no response returned]" not in rendered
    assert "unexpected status 401 Unauthorized" in rendered
    assert "api.openai.com/v1/responses" in rendered


def test_history_entry_requires_reauth_for_openai_auth_header_failure() -> None:
    module = _load_agent_console_web()

    assert (
        module._history_entry_requires_reauth(
            {
                "prompt": "status?",
                "response": "[no response returned]",
                "error": (
                    "unexpected status 401 Unauthorized: Missing bearer basic "
                    "authentication in header, url: "
                    "https://api.openai.com/v1/responses"
                ),
                "started_at": 1,
                "finished_at": 2,
                "usage": {
                    "success": False,
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            }
        )
        is True
    )


def test_auth_state_from_console_detects_openai_auth_header_failure() -> None:
    module = _load_agent_console_web()

    auth = module._auth_state_from_console(
        "",
        "unexpected status 401 Unauthorized: Missing bearer basic "
        "authentication in header, url: https://api.openai.com/v1/responses",
    )

    assert auth["required"] is True
    assert auth["mode"] == "needs_reauth"
    assert "fresh sign-in" in auth["summary"]


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
        module.update_status_meta = lambda **updates: updates

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


def test_current_snapshot_persists_cleared_trailing_reauth_history_when_ready() -> None:
    module = _load_agent_console_web()

    pane = (
        "OpenAI Codex (v0.118.0)\n"
        "model: gpt-5.4 xhigh\n"
        "directory: ~/code/norman\n"
        "› Summarize recent commits\n\n"
        "  gpt-5.4 xhigh fast · 100% left · ~/code/norman"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        history_path = state_dir / "history.jsonl"
        last_error_path = state_dir / "last_error.txt"
        thread_id_path = state_dir / "thread_id.txt"
        last_error_path.write_text(
            'ERROR refresh_token_reused: "already been used to generate a new access token"',
            encoding="utf-8",
        )
        thread_id_path.write_text("", encoding="utf-8")
        history_path.write_text(
            json.dumps(
                {
                    "prompt": "status?",
                    "response": "[no response returned]",
                    "error": 'ERROR refresh_token_reused: "already been used to generate a new access token"',
                    "started_at": 1712878340,
                    "finished_at": 1712878366,
                    "speed": "careful",
                    "detail": 3,
                    "attachments": [],
                    "usage": {
                        "success": False,
                        "total_tokens": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        module.STATE_DIR = state_dir
        module.HISTORY_PATH = history_path
        module.LAST_ERROR_PATH = last_error_path
        module.THREAD_ID_PATH = thread_id_path
        module.recover_stale_prompt_state = lambda: None
        meta = module.default_status_meta()
        meta["state"] = "ok"
        meta["status_message"] = "Ready."
        module.load_status_meta = lambda: meta

        def _safe_read_text(path, default=""):
            try:
                target = Path(path)
                if target.is_file():
                    return target.read_text(encoding="utf-8").strip()
            except OSError:
                return default
            return default

        module.read_text = _safe_read_text
        module.write_text = lambda path, value: Path(path).write_text(
            value, encoding="utf-8"
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
        persisted = [json.loads(line) for line in history_path.read_text().splitlines()]

        assert snapshot["state"] == "ok"
        assert snapshot["auth"]["required"] is False
        assert snapshot["history"] == []
        assert persisted == []


def test_current_snapshot_drops_trailing_empty_ghost_turns_when_ready() -> None:
    module = _load_agent_console_web()

    pane = (
        "OpenAI Codex (v0.118.0)\n"
        "model: gpt-5.4 xhigh\n"
        "directory: ~/code/norman\n"
        "› Summarize recent commits\n\n"
        "  gpt-5.4 xhigh fast · 100% left · ~/code/norman"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        history_path = state_dir / "history.jsonl"
        status_path = state_dir / "status.json"
        last_error_path = state_dir / "last_error.txt"
        last_prompt_path = state_dir / "last_prompt.txt"
        last_response_path = state_dir / "last_response.txt"
        thread_id_path = state_dir / "thread_id.txt"
        last_error_path.write_text("", encoding="utf-8")
        last_prompt_path.write_text("status?", encoding="utf-8")
        last_response_path.write_text("[no response returned]", encoding="utf-8")
        thread_id_path.write_text("", encoding="utf-8")
        history_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "prompt": "real prompt",
                            "response": "real response",
                            "error": "",
                            "started_at": 1712878340,
                            "finished_at": 1712878366,
                            "speed": "careful",
                            "detail": 3,
                            "attachments": [],
                            "usage": {
                                "success": True,
                                "total_tokens": 42,
                                "input_tokens": 30,
                                "output_tokens": 12,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "prompt": "status?",
                            "response": "[no response returned]",
                            "error": "",
                            "started_at": 1712878370,
                            "finished_at": 1712878372,
                            "speed": "careful",
                            "detail": 3,
                            "attachments": [],
                            "usage": {
                                "success": False,
                                "total_tokens": 0,
                                "input_tokens": 0,
                                "output_tokens": 0,
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        module.STATE_DIR = state_dir
        module.HISTORY_PATH = history_path
        module.STATUS_PATH = status_path
        module.LAST_ERROR_PATH = last_error_path
        module.LAST_PROMPT_PATH = last_prompt_path
        module.LAST_RESPONSE_PATH = last_response_path
        module.THREAD_ID_PATH = thread_id_path
        module.recover_stale_prompt_state = lambda: None
        meta = module.default_status_meta()
        meta["state"] = "error"
        meta["status_message"] = "Web prompt failed."
        meta["last_started_at"] = 1712878370
        meta["last_finished_at"] = 1712878372
        status_path.write_text(json.dumps(meta), encoding="utf-8")

        def _safe_read_text(path, default=""):
            try:
                target = Path(path)
                if target.is_file():
                    return target.read_text(encoding="utf-8").strip()
            except OSError:
                return default
            return default

        module.read_text = _safe_read_text
        module.write_text = lambda path, value: Path(path).write_text(
            value, encoding="utf-8"
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
        persisted = [json.loads(line) for line in history_path.read_text().splitlines()]
        persisted_status = json.loads(status_path.read_text(encoding="utf-8"))

        assert snapshot["state"] == "ok"
        assert len(snapshot["history"]) == 1
        assert snapshot["history"][0]["prompt"] == "real prompt"
        assert len(persisted) == 1
        assert persisted[0]["prompt"] == "real prompt"
        assert snapshot["last_prompt"] == "real prompt"
        assert snapshot["last_response"] == "real response"
        assert last_prompt_path.read_text(encoding="utf-8") == "real prompt"
        assert last_response_path.read_text(encoding="utf-8") == "real response"
        assert persisted_status["state"] == "ok"
        assert persisted_status["status_message"] == "Ready."


def test_unwind_latest_history_turn_removes_latest_turn_and_resets_thread() -> None:
    module = _load_agent_console_web()

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        history_path = state_dir / "history.jsonl"
        status_path = state_dir / "status.json"
        audit_path = state_dir / "audit.jsonl"
        last_prompt_path = state_dir / "last_prompt.txt"
        last_response_path = state_dir / "last_response.txt"
        last_error_path = state_dir / "last_error.txt"
        thread_id_path = state_dir / "thread_id.txt"
        first_entry = {
            "prompt": "Build the weekly KPI summary.",
            "response": "Weekly KPI summary is ready.",
            "error": "",
            "started_at": 1712878340,
            "finished_at": 1712878366,
            "speed": "careful",
            "detail": 3,
            "attachments": [],
            "usage": {
                "success": True,
                "total_tokens": 42,
                "input_tokens": 30,
                "output_tokens": 12,
            },
        }
        second_entry = {
            "prompt": "Proceed with the leadership KPI handoff.",
            "response": "Fubared latest reply.",
            "error": "",
            "started_at": 1712878370,
            "finished_at": 1712878394,
            "speed": "careful",
            "detail": 3,
            "attachments": [],
            "usage": {
                "success": True,
                "total_tokens": 51,
                "input_tokens": 34,
                "output_tokens": 17,
            },
        }
        history_path.write_text(
            "\n".join([json.dumps(first_entry), json.dumps(second_entry)]) + "\n",
            encoding="utf-8",
        )
        last_prompt_path.write_text(second_entry["prompt"], encoding="utf-8")
        last_response_path.write_text(second_entry["response"], encoding="utf-8")
        last_error_path.write_text("", encoding="utf-8")
        thread_id_path.write_text("thread-123", encoding="utf-8")
        status_path.write_text(
            json.dumps(
                {
                    **module.default_status_meta(),
                    "state": "ok",
                    "status_message": "Ready.",
                    "last_started_at": second_entry["started_at"],
                    "last_finished_at": second_entry["finished_at"],
                    "last_speed": second_entry["speed"],
                    "last_detail": second_entry["detail"],
                }
            ),
            encoding="utf-8",
        )

        module.STATE_DIR = state_dir
        module.HISTORY_PATH = history_path
        module.STATUS_PATH = status_path
        module.AUDIT_PATH = audit_path
        module.LAST_PROMPT_PATH = last_prompt_path
        module.LAST_RESPONSE_PATH = last_response_path
        module.LAST_ERROR_PATH = last_error_path
        module.THREAD_ID_PATH = thread_id_path

        removed = module.unwind_latest_history_turn()

        persisted = [json.loads(line) for line in history_path.read_text().splitlines()]
        persisted_status = json.loads(status_path.read_text(encoding="utf-8"))
        audit_events = [
            json.loads(line) for line in audit_path.read_text().splitlines()
        ]

        assert removed["prompt"] == second_entry["prompt"]
        assert len(persisted) == 1
        assert persisted[0]["prompt"] == first_entry["prompt"]
        assert thread_id_path.read_text(encoding="utf-8") == ""
        assert last_prompt_path.read_text(encoding="utf-8") == first_entry["prompt"]
        assert last_response_path.read_text(encoding="utf-8") == first_entry["response"]
        assert last_error_path.read_text(encoding="utf-8") == ""
        assert persisted_status["state"] == "ok"
        assert persisted_status["last_action"] == "history-unwind"
        assert (
            persisted_status["status_message"]
            == "Removed the latest turn. The next prompt will start fresh."
        )
        assert audit_events[-1]["event_type"] == "history-unwind"


def test_unwind_latest_history_turn_rejects_pending_prompt() -> None:
    module = _load_agent_console_web()

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        history_path = state_dir / "history.jsonl"
        status_path = state_dir / "status.json"
        history_path.write_text(
            json.dumps(
                {
                    "prompt": "Proceed.",
                    "response": "Latest reply.",
                    "error": "",
                    "started_at": 1712878370,
                    "finished_at": 1712878394,
                    "speed": "careful",
                    "detail": 3,
                    "attachments": [],
                    "usage": {
                        "success": True,
                        "total_tokens": 51,
                        "input_tokens": 34,
                        "output_tokens": 17,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        status_path.write_text(
            json.dumps(
                {
                    **module.default_status_meta(),
                    "pending": True,
                    "running_prompt": "Still working",
                }
            ),
            encoding="utf-8",
        )

        module.STATE_DIR = state_dir
        module.HISTORY_PATH = history_path
        module.STATUS_PATH = status_path

        with pytest.raises(RuntimeError, match="Wait for the running prompt"):
            module.unwind_latest_history_turn()


def test_current_snapshot_drops_trailing_passive_party_line_turns_when_ready() -> None:
    module = _load_agent_console_web()

    pane = (
        "OpenAI Codex (v0.118.0)\n"
        "model: gpt-5.4 xhigh\n"
        "directory: ~/code/norman\n"
        "› Summarize recent commits\n\n"
        "  gpt-5.4 xhigh fast · 100% left · ~/code/norman"
    )

    passive_prompt = (
        "[Norman Subprime party line]\n"
        "Passive fleet context only. Absorb this silently unless you are directly "
        "addressed or explicitly asked to act.\n\n"
        "Norman Subprime coordination check-in for the fleet."
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        history_path = state_dir / "history.jsonl"
        status_path = state_dir / "status.json"
        last_error_path = state_dir / "last_error.txt"
        last_prompt_path = state_dir / "last_prompt.txt"
        last_response_path = state_dir / "last_response.txt"
        thread_id_path = state_dir / "thread_id.txt"
        last_error_path.write_text("", encoding="utf-8")
        last_prompt_path.write_text(passive_prompt, encoding="utf-8")
        last_response_path.write_text("[no response returned]", encoding="utf-8")
        thread_id_path.write_text("", encoding="utf-8")
        history_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "prompt": "real prompt",
                            "response": "real response",
                            "error": "",
                            "started_at": 1712878340,
                            "finished_at": 1712878366,
                            "speed": "careful",
                            "detail": 3,
                            "attachments": [],
                            "usage": {
                                "success": True,
                                "total_tokens": 42,
                                "input_tokens": 30,
                                "output_tokens": 12,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "prompt": passive_prompt,
                            "response": "[no response returned]",
                            "error": (
                                "2026-04-09T13:21:21Z ERROR codex_core::auth: Failed "
                                "to refresh token: refresh_token_reused"
                            ),
                            "started_at": 1712878370,
                            "finished_at": 1712878372,
                            "speed": "careful",
                            "detail": 3,
                            "attachments": [],
                            "usage": {
                                "success": False,
                                "total_tokens": 0,
                                "input_tokens": 0,
                                "output_tokens": 0,
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        module.STATE_DIR = state_dir
        module.HISTORY_PATH = history_path
        module.STATUS_PATH = status_path
        module.LAST_ERROR_PATH = last_error_path
        module.LAST_PROMPT_PATH = last_prompt_path
        module.LAST_RESPONSE_PATH = last_response_path
        module.THREAD_ID_PATH = thread_id_path
        module.recover_stale_prompt_state = lambda: None
        meta = module.default_status_meta()
        meta["state"] = "ok"
        meta["status_message"] = "Ready."
        meta["last_started_at"] = 1712878370
        meta["last_finished_at"] = 1712878372
        status_path.write_text(json.dumps(meta), encoding="utf-8")

        def _safe_read_text(path, default=""):
            try:
                target = Path(path)
                if target.is_file():
                    return target.read_text(encoding="utf-8").strip()
            except OSError:
                return default
            return default

        module.read_text = _safe_read_text
        module.write_text = lambda path, value: Path(path).write_text(
            value, encoding="utf-8"
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
        persisted = [json.loads(line) for line in history_path.read_text().splitlines()]
        persisted_status = json.loads(status_path.read_text(encoding="utf-8"))

        assert snapshot["state"] == "ok"
        assert len(snapshot["history"]) == 1
        assert snapshot["history"][0]["prompt"] == "real prompt"
        assert len(persisted) == 1
        assert persisted[0]["prompt"] == "real prompt"
        assert snapshot["last_prompt"] == "real prompt"
        assert snapshot["last_response"] == "real response"
        assert last_prompt_path.read_text(encoding="utf-8") == "real prompt"
        assert last_response_path.read_text(encoding="utf-8") == "real response"
        assert persisted_status["state"] == "ok"
        assert persisted_status["status_message"] == "Ready."


def test_current_snapshot_drops_trailing_passive_party_line_turns_at_update_prompt() -> (
    None
):
    module = _load_agent_console_web()

    pane = (
        "✨ Update available! 0.116.0 -> 0.118.0\n\n"
        "› 1. Update now\n"
        "  2. Skip\n"
        "  3. Skip until next version\n\n"
        "Press enter to continue"
    )

    passive_prompt = (
        "[Norman Subprime party line]\n"
        "Passive fleet context only. Absorb this silently unless you are directly "
        "addressed or explicitly asked to act.\n\n"
        "Norman Subprime coordination check-in for the fleet."
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        history_path = state_dir / "history.jsonl"
        status_path = state_dir / "status.json"
        last_error_path = state_dir / "last_error.txt"
        last_prompt_path = state_dir / "last_prompt.txt"
        last_response_path = state_dir / "last_response.txt"
        thread_id_path = state_dir / "thread_id.txt"
        last_error_path.write_text("", encoding="utf-8")
        last_prompt_path.write_text(passive_prompt, encoding="utf-8")
        last_response_path.write_text("[no response returned]", encoding="utf-8")
        thread_id_path.write_text("", encoding="utf-8")
        history_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "prompt": "real prompt",
                            "response": "real response",
                            "error": "",
                            "started_at": 1712878340,
                            "finished_at": 1712878366,
                            "speed": "careful",
                            "detail": 3,
                            "attachments": [],
                            "usage": {
                                "success": True,
                                "total_tokens": 42,
                                "input_tokens": 30,
                                "output_tokens": 12,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "prompt": passive_prompt,
                            "response": "[no response returned]",
                            "error": "",
                            "started_at": 1712878370,
                            "finished_at": 1712878372,
                            "speed": "careful",
                            "detail": 3,
                            "attachments": [],
                            "usage": {
                                "success": False,
                                "total_tokens": 0,
                                "input_tokens": 0,
                                "output_tokens": 0,
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        module.STATE_DIR = state_dir
        module.HISTORY_PATH = history_path
        module.STATUS_PATH = status_path
        module.LAST_ERROR_PATH = last_error_path
        module.LAST_PROMPT_PATH = last_prompt_path
        module.LAST_RESPONSE_PATH = last_response_path
        module.THREAD_ID_PATH = thread_id_path
        module.recover_stale_prompt_state = lambda: None
        meta = module.default_status_meta()
        meta["state"] = "ok"
        meta["status_message"] = "Ready."
        meta["last_started_at"] = 1712878370
        meta["last_finished_at"] = 1712878372
        status_path.write_text(json.dumps(meta), encoding="utf-8")

        def _safe_read_text(path, default=""):
            try:
                target = Path(path)
                if target.is_file():
                    return target.read_text(encoding="utf-8").strip()
            except OSError:
                return default
            return default

        module.read_text = _safe_read_text
        module.write_text = lambda path, value: Path(path).write_text(
            value, encoding="utf-8"
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
        persisted = [json.loads(line) for line in history_path.read_text().splitlines()]

        assert snapshot["history"][0]["prompt"] == "real prompt"
        assert len(snapshot["history"]) == 1
        assert len(persisted) == 1
        assert snapshot["last_prompt"] == "real prompt"
        assert snapshot["last_response"] == "real response"


def test_current_snapshot_requires_reauth_when_latest_web_turn_failed_with_zero_tokens() -> (
    None
):
    module = _load_agent_console_web()

    pane = "Session encountered an authentication error and has not recovered yet."

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        history_path = state_dir / "history.jsonl"
        last_error_path = state_dir / "last_error.txt"
        last_error_path.write_text("", encoding="utf-8")
        history_path.write_text("", encoding="utf-8")
        module.STATE_DIR = state_dir
        module.HISTORY_PATH = history_path
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


def test_current_snapshot_ready_prompt_beats_stale_reauth_history() -> None:
    module = _load_agent_console_web()

    pane = "› Implement {feature}\n\n  gpt-5.4 xhigh fast · 100% left · ~/code/norman"

    with tempfile.TemporaryDirectory() as temp_dir:
        last_error_path = Path(temp_dir) / "last_error.txt"
        history_path = Path(temp_dir) / "history.jsonl"
        last_error_path.write_text(
            'ERROR refresh_token_reused: "already been used to generate a new access token"',
            encoding="utf-8",
        )
        history_path.write_text("", encoding="utf-8")
        module.STATE_DIR = Path(temp_dir)
        module.HISTORY_PATH = history_path
        module.LAST_ERROR_PATH = last_error_path
        module.recover_stale_prompt_state = lambda: None
        module.load_status_meta = lambda: {
            **module.default_status_meta(),
            "state": "error",
            "status_message": "Web prompt failed.",
        }
        module.load_history = lambda: [
            {
                "prompt": "status?",
                "response": "[no response returned]",
                "error": 'ERROR refresh_token_reused: "already been used to generate a new access token"',
                "started_at": 123,
                "finished_at": 124,
                "thread_id": "thread-123",
                "speed": "balanced",
                "detail": 3,
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

        assert snapshot["state"] == "ok"
        assert snapshot["status_message"] == "Ready."
        assert snapshot["auth"]["required"] is False
        assert snapshot["last_error"] == ""
        assert snapshot["history"] == []
        assert last_error_path.read_text(encoding="utf-8") == ""


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


def test_template_classifies_openai_transport_and_auth_failures_cleanly() -> None:
    source = _agent_console_web_source()

    assert "def _contains_openai_auth_error(text: str) -> bool:" in source
    assert "def _contains_openai_transport_error(text: str) -> bool:" in source
    assert "def _contains_cert_workflow_error(text: str) -> bool:" in source
    assert "function containsOpenAIAuthError(value) {{" in source
    assert "function containsCertWorkflowError(value) {{" in source
    assert 'title: "Cert issue"' in source
    assert 'code: "openai_transport"' in source
    assert "!isPlaceholderAssistantResponse(snapshot.last_response)" in source
    assert (
        'isPlaceholderAssistantResponse(item.response) && String(item.error || "").trim()'
        in source
    )


def test_template_collapses_long_error_cards_into_expandable_details() -> None:
    source = _agent_console_web_source()

    assert "function renderErrorMarkup(value) {{" in source
    assert "function shouldCollapseErrorDetails(value) {{" in source
    assert 'text.innerHTML = cleanRole.includes("error")' in source
    assert 'class="error-inline-summary"' in source
    assert 'class="error-details"' in source


def test_cert_workflow_errors_are_classified_cleanly() -> None:
    module = _load_agent_console_web()

    assert module._contains_cert_workflow_error(
        "ssl certificate verify failed while make_cert retried the request"
    )
    assert module._snapshot_tone_label(
        {
            "pane": "",
            "last_error": "certificate_verify_failed: tls handshake failed",
            "pending": False,
            "state": "error",
        }
    ) == ("error", "Cert issue")


def test_template_uses_edge_to_edge_shell_frame() -> None:
    source = _agent_console_web_source()

    assert "max-width: none;" in source
    assert "width: 100%;" in source
    assert "--workspace-edge-pad: clamp(2px, 0.45vw, 8px);" in source
    assert "padding: 0 var(--workspace-edge-pad) var(--workspace-edge-pad);" in source
    assert "padding: 2px var(--mobile-edge-pad) 3px;" in source
    assert "width: calc(100vw - 4px);" in source


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
    assert "const liveStatusBody = liveStatusBodyForSnapshot(" in source
    assert "function liveStatusBodyForSnapshot(" in source


def test_template_animates_microtextures_with_worker_state() -> None:
    source = _agent_console_web_source()

    assert 'data-microtexture-state="idle"' in source
    assert 'id="microtexture-thread-field"' in source
    assert ".microtexture-thread-field {{" in source
    assert "const MICROTEXTURE_FIELD_PROFILES = Object.freeze({{" in source
    assert "const MICROTEXTURE_THREAD_PROFILES = Object.freeze({{" in source
    assert "function applyMicrotextureFieldProfile(stateKey) {{" in source
    assert "function startMicrotextureThreadField() {{" in source
    assert "function drawMicrotextureThreadField(timestampMs = 0) {{" in source
    assert "function microtextureFluidSquareWave(value, squareWeight) {{" in source
    assert (
        "function microtextureFractalSquareWave(value, squareWeight, phase = 0) {{"
        in source
    )
    assert "function drawMicrotextureThreadSegment(" in source
    assert 'function pulseMicrotextureThreadField(kind = "tick") {{' in source
    assert (
        "function syncMicrotextureState(snapshot, auth, humanAsk, queueDepth, bbsSignal) {{"
        in source
    )
    assert (
        'function triggerMicrotexturePulse(kind = "tick", options = {{}}) {{' in source
    )
    assert "function snapshotMicrotextureCounters(snapshot) {{" in source
    assert 'body[data-microtexture-state="working"]::before,' in source
    assert 'body[data-microtexture-state="degraded"]::before,' in source
    assert 'body[data-microtexture-state="crashed"]::before {{' in source
    assert 'body[data-microtexture-pulse="tool"]::after' in source
    assert "@keyframes microtexture-click-ripple {{" in source
    assert "@keyframes microtexture-fault-shear {{" in source
    assert "@keyframes microtexture-field-flow {{" not in source
    assert "@keyframes microtexture-wisp-flow {{" not in source
    assert "linear-gradient(92deg" not in source
    assert "linear-gradient(88deg" not in source
    assert "860px 420px" not in source
    assert "980px 360px" not in source
    assert "background-repeat: no-repeat;" in source
    assert "microtexture-field-flow var(--microtexture-drift-duration)" not in source
    assert "microtexture-wisp-flow var(--microtexture-wisp-duration)" not in source
    assert "--microtexture-drift-duration: 7.5s;" in source
    assert "--microtexture-drift-x: 148px;" in source
    assert "--microtexture-glint-duration: 7.5s;" in source
    assert "--microtexture-thread-opacity: 0.38;" in source
    assert '"--microtexture-drift-duration": "7.5s",' in source
    assert '"--microtexture-thread-opacity": "0.38",' in source
    assert '"--microtexture-drift-duration": "18s",' in source
    assert '"--microtexture-drift-duration": "11s",' in source
    assert "speed: 0.64, drift: 34, amplitude: 5.8" in source
    assert "square: 0.74, shear: -0.09" in source
    assert "meshSpacing: 54" in source
    assert (
        "function microtextureInterpolatedThreadProfile(targetProfile, deltaSeconds) {{"
        in source
    )
    assert (
        "function microtextureBlendNumber(currentValue, targetValue, amount) {{"
        in source
    )
    assert (
        "function microtextureThreadDomainWarp(thread, parameter, metrics) {{" in source
    )
    assert "function microtextureThreadEnvelope(thread, metrics) {{" in source
    assert "const golden = 1.618033988749895;" in source
    assert "state.microtextureThreadRenderProfile = next;" in source
    assert 'addThread("h", index, rowCount, width);' in source
    assert 'addThread("v", index, columnCount, height);' in source
    assert "flowDirection: 1," in source
    assert 'harmonicOffset: microtextureSeed(index, axis === "v" ? 13 : 17),' in source
    assert "thread.reverse" not in source
    assert (
        "const oneWayFlow = Math.max(0, Number(metrics.flowOffset || 0)) * thread.flowDirection;"
        in source
    )
    assert "flowOffset," in source
    assert 'context.globalCompositeOperation = "source-over";' in source
    assert "const gradient = context.createLinearGradient(" in source
    assert 'thread.axis === "h" && glintStrength > 0.01' in source
    assert "radial-gradient(circle at var(--microtexture-pulse-x)" not in source
    assert "radial-gradient(ellipse at 12%" not in source
    assert "radial-gradient(ellipse at 74%" not in source
    assert 'body[data-microtexture-state="flow"]::before {{' in source
    assert "--microtexture-drift-duration: 4.8s;" in source
    assert "--microtexture-drift-x: 230px;" in source
    assert "calc(var(--microtexture-drift-x) * 0.82) 0" not in source
    assert "118vw 0" not in source
    assert "transform: translate3d(136%, 0, 0) scaleX(1.02);" not in source
    assert "transform: translate3d(112%, 0, 0) scaleX(1);" in source
    assert "infinite alternate" not in source
    assert "@keyframes microtexture-blocked-jitter {{" not in source
    assert 'return "working";' in source
    assert 'return "flow";' in source
    assert 'return "degraded";' in source
    assert 'return "crashed";' in source
    assert "syncMicrotextureState(" in source
    assert "document.body.dataset.microtextureState = cleanState;" in source
    assert "syncMicrotextureThreadProfile(cleanState);" in source
    assert (
        "state.microtextureThreadFrame = window.requestAnimationFrame(drawMicrotextureThreadField);"
        in source
    )
    assert "body.dataset.microtexturePulse = cleanKind;" in source
    assert "pulseMicrotextureThreadField(cleanKind);" in source
    assert (
        "microtexturePulseKindFromDelta(counters, state.microtextureCounters, nextState)"
        in source
    )
    assert 'body[data-microtexture-state="working"] .topbar.surface::before' in source


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
    assert "0 16px 36px rgba(8, 12, 18, 0.14)," in source
    assert "backdrop-filter: blur(14px) saturate(118%);" in source
    assert ".rich-table th + th," in source
    assert ".context-save-button {" in source
    assert '.context-save-button[data-save-tone="danger"] {' in source
    assert ".kpi-strip {" in source
    assert ".kpi-capsule {" in source
    assert ".system-runtime-metrics {" in source
    assert "body.mobile-compose-mode .message-tools," in source
    assert "body.mobile-compose-mode #switcher-toggle-button {" in source


def test_template_adds_dense_menu_tooltips_and_icon_choices() -> None:
    source = _agent_console_web_source()

    assert "[data-tooltip]:not([data-governance-action])::after {" in source
    assert 'data-tooltip="Console controls"' in source
    assert 'data-tooltip="Add file, screenshot, or context"' in source
    assert 'data-tooltip-side="left"' in source
    assert "function hydrateControlTooltips(root = document) {" in source
    assert 'control.dataset.tooltipFromTitle = "true";' in source
    assert "hydrateControlTooltips();" in source
    assert ".topbar-menu::before {" in source
    assert ".topbar-menu-links--context {" in source
    assert ".composer-upload-item[data-icon]::before," in source
    assert 'aria-label="Refresh live status"' in source
    assert 'data-tooltip="Attach recent logs"' in source


def test_template_uses_agent_marks_and_orbit_tab_chrome() -> None:
    source = _agent_console_web_source()

    assert "ENTITY_MARK_ALIASES" in source
    assert "const AGENT_MARK =" in source
    assert "const TAB_TITLE_LABEL =" in source
    assert "const FAVICON_AGENT_PALETTE =" in source
    assert "function syncTabFaviconMotion(descriptor)" in source
    assert "buildStateFaviconHref(descriptor, frame = 0)" in source
    assert "identity.accent || descriptor.border" in source
    assert "identity.surface || 'rgba(255,255,255,0.055)'" in source
    assert 'descriptor.key === "ready" && queueDepth <= 0' in source


def test_launch_template_includes_norman_broker_policy() -> None:
    source = _agent_console_launch_source()

    assert "Fleet coordination policy:" in source
    assert (
        "Norman Prime / the Norman session is always an allowed coordination target"
        in source
    )
    assert "Subprime is Norman's coordination/backchannel lane." in source
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
    assert "Treat Norman Subprime as the persistent party line" in source
    assert "Do not recommend on-demand instances as the default answer." in source
    assert "Prefer bullets, short sections, compact key-value lists" in source
    assert "Treat most TUI/web bot surfaces as the slow/default-cost path" in source
    assert "Norman Prime on norman.home.arpa is allowed to use the fast path" in source
    assert "Norman Switchboard party-line broadcast" in source
    assert "Absorb it quietly unless you are directly addressed" in source
    assert "you are already in the live Norman coordination channel" in source
    assert "Do not say that Subprime is unavailable" in source
    assert "treat the current conversation as the live party line" in source


def test_launch_template_quarantines_external_auth_symlinks() -> None:
    source = _agent_console_launch_source()

    assert 'AUTH_FILE="${CODEX_HOME}/auth.json"' in source
    assert 'if [[ -L "$AUTH_FILE" ]]; then' in source
    assert 'CODEX_HOME_REALPATH="$(readlink -f "$CODEX_HOME"' in source
    assert 'AUTH_REALPATH="$(readlink -f "$AUTH_FILE"' in source
    assert 'AUTH_BACKUP="${CODEX_HOME}/auth.json.broken-external-' in source
    assert 'mv "$AUTH_FILE" "$AUTH_BACKUP"' in source
    assert "Quarantined external auth.json symlink" in source


def test_completion_bell_settings_and_reply_hook_are_present() -> None:
    source = _agent_console_web_source()

    assert 'data-setting="completionBell"' in source
    assert 'id="completion-bell-test-button"' in source
    assert "const COMPLETION_BELL_PROFILES = {{" in source
    assert "voices: [" in source
    assert "answer: {{" in source
    assert (
        "const AGENT_COMPLETION_BELL_PROFILE = buildAgentCompletionBellProfile();"
        in source
    )
    assert "if (AGENT_COMPLETION_BELL_PROFILE) {{" in source
    assert 'const profile = key === "agent"' in source
    assert (
        "function scheduleCompletionBellVoice(ctx, destination, profile, voice, startTime) {{"
        in source
    )
    assert "function playCompletionBell(options = {{}})" in source
    assert "playCompletionBell();" in source


def test_broker_ui_mentions_norman_subprime_architecture() -> None:
    source = _agent_console_web_source()

    assert "Confirm Switchboard is reachable." in source
    assert "Norman/Subprime" in source
    assert "Switchboard" in source and "Subprime" in source


def test_template_applies_subtle_per_agent_style_variants() -> None:
    source = _agent_console_web_source()

    assert "STYLE_VARIANTS: dict[str, dict[str, str]] = {" in source
    assert "AGENT_STYLE_VARIANT_OVERRIDES = {" in source
    assert 'data-setting="styleVariant"' in source
    assert "const STYLE_VARIANT_MAP =" in source
    assert "def style_variant_vars_css(agent_key: str) -> str:" in source
    assert "--style-variant-name:" in source
    assert "const AGENT_STYLE_VARIANT =" in source
    assert 'styleVariant: "auto"' in source
    assert "function normalizeStyleVariant(value) {" in source
    assert (
        "function resolvedStyleVariantKey(value = state.preferences?.styleVariant) {"
        in source
    )
    assert "function applyStyleVariantPreference() {" in source
    assert "{style_variant_vars_css(AGENT_SLUG)}" in source
    assert "document.body.dataset.styleVariant = key;" in source
    assert "linear-gradient(var(--body-accent-angle)" in source
    assert "opacity: calc(var(--body-overlay-opacity) * 0.42);" in source
    assert "border-radius: var(--brand-radius);" in source
    assert "border-radius: var(--chrome-pill-radius);" in source
    assert "font-family: var(--font-reading);" in source


def test_template_uses_poppins_for_openbrand_work_surfaces() -> None:
    source = _agent_console_web_source()

    assert "def agent_font_vars_css(agent_key: str) -> str:" in source
    assert "OPENBRAND_FONT_AGENT_SLUGS = {" in source
    assert '"pefb"' in source
    assert (
        'if semantic_group == "work" or agent_key in OPENBRAND_FONT_AGENT_SLUGS:'
        in source
    )
    assert '"Poppins", "IBM Plex Sans"' in source
    assert "{agent_font_vars_css(AGENT_SLUG)}" in source
    assert "family=Poppins:wght@400;500;600;700" in source


def test_template_exposes_common_reply_shortcuts() -> None:
    source = _agent_console_web_source()

    assert "const REPLY_ACTIONS = {{" in source
    assert 'label: "Make it so"' in source
    assert 'label: "Proceed"' in source
    assert 'label: "Simpler"' in source
    assert "function replyShortcutDescriptor(kind, seed, offset = 0)" in source
    assert (
        "function replyShortcutDescriptors(sourcePrompt, body, options = {{}})"
        in source
    )
    assert (
        "function buildReplyShortcutGroup(sourcePrompt, body, options = {{}})" in source
    )
    assert "function submitPromptSuggestion(prompt) {{" in source
    assert 'group.className = String(options.className || "reply-shortcuts");' in source
    assert 'className: "reply-tail-actions"' in source
    assert 'buttonClass: "ghost inline-action reply-tail-action"' in source
    assert "if (options.submitImmediately) {{" in source
    assert "submitPromptSuggestion(descriptor.prompt);" in source
    assert "submitImmediately: true," in source
    assert 'applyPromptSuggestion(button.dataset.suggestion || "");' in source
    assert 'copyQuick.textContent = "Copy";' in source
    assert 'copyQuick.title = "Copy plain text";' in source
    assert "plainTextFromRenderedMessage(article, body)" in source
    assert ".reply-tail-actions::-webkit-scrollbar {" in source
    assert ".reply-tail-action {" in source


def test_template_exposes_latest_turn_unwind_control() -> None:
    source = _agent_console_web_source()

    assert "def unwind_latest_history_turn() -> dict[str, Any]:" in source
    assert 'if parsed.path in {"/api/history/unwind", "/history/unwind"}:' in source
    assert 'button.textContent = "Unwinding…";' in source
    assert 'const result = await postForm("/api/history/unwind", {{}});' in source
    assert 'unwindQuick.textContent = "Unwind";' in source
    assert 'unwindButton.textContent = "Unwind";' in source
    assert "canUnwindLatestTurn" in source


def test_template_normalizes_message_copy_to_plain_text() -> None:
    source = _agent_console_web_source()

    assert "function normalizeCopiedText(value) {{" in source
    assert "function plainTextFromNode(node) {{" in source
    assert 'function plainTextFromRenderedMessage(article, fallback = "") {{' in source
    assert "function selectionPlainTextFromUi() {{" in source
    assert 'document.addEventListener("copy", (event) => {{' in source
    assert 'event.clipboardData.setData("text/plain", value);' in source


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
    assert "INLINE_BOT_ENTITY_DEFS" in source
    assert "INLINE_PERSON_ENTITY_DEFS" in source
    assert "INLINE_LOCATION_ENTITY_DEFS" in source
    assert "const INLINE_ENTITY_DEFS =" in source
    assert "function buildInlineEntityEntries(defs) {{" in source
    assert "function highlightInlineEntities(text) {{" in source
    assert "function highlightDynamicHostEntities(text, stashMarkup) {{" in source
    assert "function entityDecoratorForKind(kind) {{" in source
    assert 'class="entity-cartouche"' in source
    assert ".message-body .entity-cartouche," in source
    assert 'data-kind="${{escapeHtml(kind)}}"' in source
    assert 'data-decorator="${{escapeHtml(decorator)}}"' in source
    assert 'data-mention="true"' in source
    assert 'data-kind="person"' in source
    assert 'data-kind="location"' in source


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
    assert "function usageCapsuleState(snapshot) {" in source
    assert "function inferBackgroundTask(snapshot = state.snapshot) {" in source
    assert "function backgroundWorkState(snapshot) {" in source
    assert 'value: "Job live"' in source
    assert 'title: "Background run active"' in source
    assert 'label: "Background"' in source
    assert 'id: "background"' in source
    assert "function buildStatusCapsules(snapshot) {" in source
    assert "function renderStatusCapsules(snapshot) {" in source
    assert "function renderSystemRuntimeMetrics(snapshot) {" in source
    assert 'button.dataset.kpiAction = String(item.action || "system");' in source
    assert 'const action = String(capsule.dataset.kpiAction || "system");' in source
    assert 'if (action === "notices") {' in source
    assert 'else if (action === "peek") {' in source
    assert "function backgroundMonitorNotice(snapshot = state.snapshot) {" in source
    assert "const background = backgroundMonitorNotice(snapshot);" in source
    assert "const backgroundItems = background && !background.intervention" in source


def test_template_exposes_lightweight_version_endpoint() -> None:
    source = _agent_console_web_source()

    assert 'if parsed.path == "/api/version":' in source
    assert '"ui_version": UI_VERSION' in source
    assert '"agent_name": AGENT_NAME' in source
    assert '"session_name": SESSION' in source


def test_template_surfaces_offline_spark_runtime_detail() -> None:
    source = _agent_console_web_source()

    assert "function localLlmDetails(snapshot) {" in source
    assert "function offlineLlmState(snapshot) {" in source
    assert "function sparkMeshState(snapshot) {" in source
    assert "function warmSetState(snapshot) {" in source
    assert "function specialistProofState(snapshot) {" in source
    assert "function compactProofCountMap(map, limit = 3) {" in source
    assert "function plannerPreflightState(snapshot) {" in source
    assert "function kernelShadowState(snapshot) {" in source
    assert "capabilitySummary" in source
    assert "runtime_capabilities" in source
    assert "local_first_proof" in source
    assert "norman.norllama.specialist-proof.v1" in source
    assert 'value = "Catalog ready";' in source
    assert '"Warm policy pending"' in source
    assert 'id: "offline-llm"' in source
    assert 'id: "specialist-proof"' in source
    assert 'label: "Offline AI"' in source
    assert 'label: "Spark mesh"' in source
    assert 'label: "Warm set"' in source
    assert 'label: "Specialist proof"' in source
    assert 'label: "Planner"' in source
    assert 'label: "Kernel shadow"' in source
    assert 'data-tone="${{escapeHtml(String(item.tone || "neutral"))}}"' in source
    assert '.system-runtime-metric[data-tone="active"] {' in source
    assert '.system-runtime-metric[data-tone="warn"] {' in source
    assert '.system-runtime-metric[data-tone="alert"] {' in source
    assert '.system-runtime-metric[data-wide="true"] {' in source


def test_tui_uses_render_caches_and_background_transport_backoff() -> None:
    source = _agent_console_web_source()

    assert "renderCache: {{" in source
    assert "function conversationRenderSignature(snapshot) {{" in source
    assert "if (state.renderCache.conversation === renderKey) {{" in source
    assert "function disconnectStream() {{" in source
    assert "function syncLiveTransport() {{" in source
    assert "document.hidden" in source
    assert "const VISIBLE_PENDING_STATUS_POLL_MS = 2000;" in source
    assert "const VISIBLE_IDLE_STATUS_POLL_MS = 12000;" in source
    assert "const BACKGROUND_PENDING_STATUS_POLL_MS = 12000;" in source
    assert "const BACKGROUND_IDLE_STATUS_POLL_MS = 30000;" in source
    assert "? (state.snapshot.pending ? 12000 : 30000)" in source
    assert (
        ": (state.snapshot.pending ? VISIBLE_PENDING_STATUS_POLL_MS : VISIBLE_IDLE_STATUS_POLL_MS)"
        in source
    )
    assert (
        'setTransportState(state.snapshot.pending ? "Background · waiting" : "Background", false);'
        in source
    )
    assert (
        'state.transportLabel = String(label || "").trim() || "Connecting…";' in source
    )
    assert "renderStatusCapsules(state.snapshot);" in source
    assert "renderSystemRuntimeMetrics(state.snapshot);" in source
    assert "normalizeTransportLabel(" in source
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
    module.THREAD_SCOPE_PATH = state_dir / "thread_scope.txt"
    original_popen = module.subprocess.Popen
    original_communicate = module.communicate_with_prompt_timeout
    original_codex_bin = module.CODEX_BIN
    seen_cmd = []

    class _FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen_cmd[:] = cmd

    def _fake_communicate(popen, timeout_seconds, **kwargs):
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "last_message.txt").write_text("ok", encoding="utf-8")
        return (
            '{"type":"thread.started","thread_id":"thread-usage"}\n'
            '{"type":"turn.completed","usage":{"input_tokens":321,"cached_input_tokens":45,"output_tokens":29}}\n',
            (
                "Warning: no last agent message; wrote empty content to "
                f"{state_dir}/last_message.txt\n"
            ),
            False,
        )

    try:
        module.CODEX_BIN = "/tmp/test-codex-bin"
        module.subprocess.Popen = _FakePopen
        module.communicate_with_prompt_timeout = _fake_communicate
        module.update_live_turn_prompt_estimate = lambda **kwargs: None
        module.set_active_codex_process = lambda value: None
        response, error_text, thread_id, usage = module._execute_codex_prompt(
            "hello", "slow", 1, []
        )
    finally:
        module.subprocess.Popen = original_popen
        module.communicate_with_prompt_timeout = original_communicate
        module.CODEX_BIN = original_codex_bin

    assert seen_cmd[0] == "/tmp/test-codex-bin"
    assert response == "ok"
    assert error_text == ""
    assert thread_id == "thread-usage"
    assert usage["input_tokens"] == 321
    assert usage["cached_input_tokens"] == 45
    assert usage["output_tokens"] == 29
    assert usage["total_tokens"] == 350


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
        usage={
            "input_tokens": 120,
            "cached_input_tokens": 30,
            "output_tokens": 18,
            "preflight_prompt_estimated_tokens": 200_000,
            "attachment_saved_tokens": 500,
            "local_preflight_tokens": 25,
            "context_pack_saved_tokens": 1_500,
            "cloud_tokens_avoided_floor": 2_000,
            "cloud_tokens_avoided_estimate": 2_000,
            "cloud_preflight_net_token_delta_estimate": 1_975,
            "cloud_context_gate_active": True,
            "cloud_context_gate_status": "preflighted",
        },
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
    assert snapshot["current_thread"]["local_preflight_tokens"] == 25
    assert snapshot["current_thread"]["cloud_tokens_avoided_floor"] == 2_000
    assert snapshot["current_thread"]["cloud_context_gate_active_turns"] == 1
    assert snapshot["current_thread"]["cloud_context_gate_needs_reduction_turns"] == 0
    assert snapshot["last_turn"]["thread_id"] == "recent"
    assert snapshot["last_turn"]["total_tokens"] == 138
    assert snapshot["last_turn"]["cloud_preflight_net_token_delta_estimate"] == 1_975


def test_usage_snapshot_reports_route_utilization() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    entries = [
        {
            "started_at": now - module.USAGE_WINDOW_SECONDS - 180,
            "finished_at": now - module.USAGE_WINDOW_SECONDS - 120,
            "thread_id": "older",
            "runtime": "codex",
            "model": "gpt-5",
            "provider_surface": "openai-direct",
            "success": True,
            "input_tokens": 900,
            "output_tokens": 99,
            "total_tokens": 999,
        },
        {
            "started_at": now - 120,
            "finished_at": now - 90,
            "thread_id": "recent",
            "runtime": "localllm",
            "model": "qwen3-coder-next:q4_K_M",
            "provider_surface": "norllama",
            "success": True,
            "input_tokens": 40,
            "output_tokens": 10,
            "total_tokens": 50,
        },
        {
            "started_at": now - 80,
            "finished_at": now - 45,
            "thread_id": "recent",
            "runtime": "codex",
            "model": "gpt-5",
            "provider_surface": "aws-bedrock",
            "success": True,
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "local_preflight_tokens": 25,
            "cloud_tokens_avoided_floor": 2000,
            "cloud_tokens_avoided_estimate": 2000,
            "cloud_preflight_net_token_delta_estimate": 1975,
            "cloud_context_gate_active": True,
            "cloud_context_gate_status": "preflighted",
        },
    ]

    snapshot = module.usage_snapshot(entries, thread_id="recent")
    route = snapshot["route_utilization"]
    recent = route["last_24h"]
    current_thread = route["current_thread"]

    assert route["schema"] == "norman.tui.route-utilization.v1"
    assert route["totals"]["turns"] == 3
    assert route["totals"]["cloud_turns"] == 2
    assert recent["turns"] == 2
    assert recent["successful_turns"] == 2
    assert recent["local_turns"] == 1
    assert recent["norllama_turns"] == 1
    assert recent["cloud_turns"] == 1
    assert recent["bedrock_turns"] == 1
    assert recent["local_assisted_turns"] == 2
    assert recent["local_preflight_turns"] == 1
    assert recent["cloud_context_gate_turns"] == 1
    assert recent["local_tokens"] == 75
    assert recent["cloud_tokens"] == 150
    assert recent["cloud_tokens_avoided_estimate"] == 2000
    assert recent["cloud_preflight_net_token_delta_estimate"] == 1975
    assert recent["local_turn_rate"] == 0.5
    assert recent["local_assist_rate"] == 1.0
    assert recent["cloud_token_avoidance_rate"] == round(2000 / 2150, 4)
    assert current_thread["turns"] == 2
    assert current_thread["local_assisted_turns"] == 2

    enriched = module.route_utilization_with_live_activity(
        route,
        {
            "status": "active",
            "tool_call_count": 3,
            "source_count": 2,
            "capability_counts": {"rerank": 1, "embed": 2},
            "latest_tool_call": {
                "capability": "rerank",
                "model": "bge-m3:latest",
                "worker_id": "spark-150",
            },
        },
        {"count": 2, "ok": 1, "fail": 1},
    )

    live = enriched["live_tool_activity"]
    assert live["tool_call_count"] == 3
    assert live["capability_counts"]["embed"] == 2
    assert live["route_outcome_count"] == 2
    assert live["route_outcome_ok"] == 1
    assert live["route_outcome_fail"] == 1


def test_usage_api_payload_defaults_to_compact_route_utilization() -> None:
    module = _load_agent_console_web()
    state_dir = Path(tempfile.mkdtemp()) / "state"
    module.STATE_DIR = state_dir
    module.USAGE_PATH = state_dir / "usage.jsonl"

    now = int(time.time())
    module.append_usage_entry(
        started_at=now - 40,
        finished_at=now - 20,
        thread_id="recent",
        runtime="codex",
        model="gpt-5",
        speed="fast",
        detail=2,
        success=True,
        usage={
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "local_preflight_tokens": 25,
            "local_specialist_used": True,
            "local_specialist_tokens": 17,
            "cloud_tokens_avoided_estimate": 2000,
        },
    )

    payload = module.usage_api_payload(thread_id="recent")

    assert payload["schema"] == "norman.tui.usage-api.v1"
    assert payload["ui_version"] == module.UI_VERSION
    assert payload["agent_name"] == module.AGENT_NAME
    usage = payload["usage"]
    assert "recent" not in usage
    assert "billing" not in usage
    assert usage["current_thread"]["turns"] == 1
    route = usage["route_utilization"]["last_24h"]
    assert route["local_assisted_turns"] == 1
    assert route["local_preflight_turns"] == 1
    assert route["local_specialist_turns"] == 1
    assert route["local_specialist_tokens"] == 17

    verbose = module.usage_api_payload(include_recent=True, include_billing=True)
    assert "recent" in verbose["usage"]
    assert "billing" in verbose["usage"]


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
    assert "Subprime" in template
    assert ">Open Subprime</a>" in template
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
    assert "Send to Subprime" in template


def test_base_nav_splits_chat_and_dashboard_routes() -> None:
    routes = (Path(__file__).resolve().parents[1] / "app" / "app_routes.py").read_text(
        encoding="utf-8"
    )
    template = _base_template_source()
    styles = _styles_source()

    assert 'href="/bot/norman/"' in template
    assert ">Chat</a>" in template
    assert 'href="/dashboard.html?view=switchboard"' in template
    assert ">Switchboard</a>" in template
    assert 'id="normanShellMenu"' in template
    assert "norman-shell-menu__sheet" in template
    assert "Control Plane" in template
    assert ">Subprime lane</a>" in template
    assert ">Directory</a>" in template
    assert ">Settings</a>" in template
    assert ">Connectors</a>" in template
    assert ">Sources</a>" in template
    assert ">Filters</a>" in template
    assert ">Actions</a>" in template
    assert "site-banner--norman-shell" in template
    assert "container-fluid lower-deck-main my-3" in template
    assert (
        "brand-sub\">{% if active_page == 'home' %}Switchboard{% elif active_page == 'messages' %}Super TUI{% elif active_page == 'login' %}Sign In{% else %}Control Plane{% endif %}"
        in template
    )
    assert "body.page-systems," in styles
    assert "body.page-settings {" in styles
    assert ".subpage-shell .input-group-text {" in styles
    assert '@app_routes.get("/dashboard")' in routes
    assert '@app_routes.get("/dashboard.html")' in routes
    assert '@app_routes.get("/switchboard")' in routes
    assert '@app_routes.get("/switchboard.html")' in routes
    assert (
        "return RedirectResponse(url=_norman_chat_redirect_url(request), status_code=307)"
        in routes
    )
    assert (
        'return f"/bot/norman/?{urlencode(params)}" if params else "/bot/norman/"'
        in routes
    )
    assert 'return "/dashboard.html?view=switchboard"' in routes


def test_switchboard_and_directory_crosslink_dohio_topology() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = (root / "db" / "estate" / "registry.yaml.dist").read_text(
        encoding="utf-8"
    )
    systems_template = (root / "app" / "templates" / "systems.html").read_text(
        encoding="utf-8"
    )
    home_js = _home_js_source()
    systems_js = _systems_js_source()

    assert "dohio-topology" in registry
    assert "switchyard-network-board" in registry
    assert "https://dohio.home.arpa/" in registry
    assert "https://dohio.home.arpa/" in _index_template_source()
    assert "https://dohio.home.arpa/" in systems_template
    assert "'dohio-topology': 'dohio.home.arpa'" in home_js
    assert "'dohio-topology': 'dohio.home.arpa'" in systems_js
    assert "'switchyard-network-board': 'dohio.home.arpa/admin'" in systems_js


def test_tui_menu_can_surface_norman_backend_links() -> None:
    source = _agent_console_web_source()

    assert 'in {"norman", "pipeline"}' in source
    assert "topbar-menu-links topbar-menu-links--context" in source


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
    assert 'id="messages-prime-layer-toggle"' in template
    assert 'id="messages-prime-layer-frame"' in template
    assert 'data-src="{{ dashboard_embed_url }}"' in template
    assert 'data-open="false"' in template
    assert 'id="messages-prime-layer-body" hidden' in template
    assert "Embedded Norman Prime" in template
    assert "Prime Deck" in template
    assert "streams-advanced-control" in template
    assert "Gold super TUI on top." in template
    assert "function initSuperTuiPrimeLayer()" in js
    assert "SUPER_TUI_PRIME_OPEN_KEY" in js
    assert "return false;" in js
    assert "toggle.textContent = next ? 'Hide Prime' : 'Prime Deck';" in js
    assert ".messages-prime-layer {" in styles
    assert "body.page-messages .messages-page--super .messages-chat-card" in styles
    assert "body.embed-mode" in styles


def test_home_prime_buries_legacy_dashboard_in_lower_deck() -> None:
    template = (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "index.html"
    ).read_text(encoding="utf-8")
    styles = _styles_source()

    assert 'class="home-prime__lower-deck"' in template
    assert "Switchboard map, directory, and buried control surfaces" in template
    assert '<div class="home-grid">' in template
    assert ".home-prime__lower-deck {" in styles
    assert ".home-prime__lower-deck-summary" in styles
    assert "body.home-mode .home-prime {" in styles
    assert "--prime-link: #f0ca79;" in styles
    assert 'href="/bot/subprime/"' in template
    assert ">Open Subprime</a>" in template
    assert 'href="/bot/norman/"' in template
    assert ">Norman</a>" in template
    assert ">Open lane</a>" in template
    assert '<span class="home-mobile-deck__label">Norman</span>' in template


def test_home_prime_surfaces_llm_runtime_status() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    styles = _styles_source()
    js = (root / "app" / "static" / "js" / "home.js").read_text(encoding="utf-8")

    assert 'id="home-prime-llm-status"' in template
    assert 'id="home-prime-llm-ping"' in template
    assert 'id="home-prime-llm-summary"' in template
    assert 'id="home-prime-llm-items"' in template
    assert "Checking model durability lane" in template
    assert ".home-prime__section-tools" in styles
    assert ".home-prime__llm-summary," in styles
    assert "function renderPrimeLlmStatus(payload)" in js
    assert "async function loadPrimeLlmStatus" in js
    assert "async function runPrimeLlmPing()" in js
    assert "fetchJson('/api/llm/status')" in js
    assert "postJson('/api/llm/ping', {})" in js
    assert "llmProviderEndpoint" in js


def test_norman_login_uses_gold_super_tui_shell() -> None:
    template = (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "login.html"
    ).read_text(encoding="utf-8")
    styles = _styles_source()

    assert "norman-auth-shell" in template
    assert "Control Plane Sign In" in template
    assert "Enter Norman" in template
    assert ".norman-auth-shell {" in styles
    assert ".norman-auth-card {" in styles
    assert "body.page-login," in styles


def test_legacy_norman_subpages_share_tui_shell_actions() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    styles = _styles_source()
    systems = (root / "systems.html").read_text(encoding="utf-8")
    connectors = (root / "connectors.html").read_text(encoding="utf-8")
    channels = (root / "channels.html").read_text(encoding="utf-8")
    filters = (root / "filters.html").read_text(encoding="utf-8")
    actions = (root / "actions.html").read_text(encoding="utf-8")
    settings = (root / "settings.html").read_text(encoding="utf-8")
    messages = _messages_log_template_source()

    for template in (systems, connectors, channels, filters, actions, settings):
        assert "subpage-eyebrow" in template
        assert "subpage-actions" in template
        assert 'href="/bot/norman/"' in template
        assert 'href="/dashboard.html?view=switchboard"' in template

    assert 'href="/bot/subprime/"' in systems
    assert 'href="/bot/subprime/"' in settings
    assert ">Norman</a>" in systems
    assert "Norman Chat" in messages
    assert "font-family: 'Space Grotesk'" in styles
    assert "font-family: inherit;" in styles
    assert ".subpage-eyebrow {" in styles
    assert ".subpage-actions {" in styles
    assert ".subpage-shell::before {" in styles
    assert ".subpage-shell .page-header {" in styles
    assert ".subpage-shell .alert {" in styles
    assert ".subpage-shell input:-webkit-autofill," in styles
    assert ".subpage-shell .btn-primary {" in styles
    assert ".settings-layout {" in styles
    assert ".settings-stack {" in styles
    assert ".site-banner--norman-shell .norman-shell-menu__sheet {" in styles


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
            "OpenAI Codex (v0)\ndirectory: /home/kristopher/code/control_plane",
        ]
    )
    sent: list[list[str]] = []

    def _capture() -> str:
        try:
            return next(panes)
        except StopIteration:
            return "OpenAI Codex (v0)\ndirectory: /home/kristopher/code/control_plane"

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


def test_render_index_exposes_visible_enter_shortcut_hint() -> None:
    source = _agent_console_web_source()

    assert (
        "Queue prompt. Press Enter to queue and Shift+Enter for a new line." in source
    )


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
        "- `Management` `025066255943`\n- `Log Archive` `084005163213`",
        token="open-sesame",
        profile="personal-2",
        route="host",
    )

    assert "<code>Management</code>" in rendered
    assert "<code>025066255943</code>" in rendered
    assert "`Management`" not in rendered
    assert "`025066255943`" not in rendered


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
    handler.client_address = ("192.168.2.241", 443)
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
        codex_home="/home/kristopher/.codex-control-plane",
    )

    rendered = module.render_host_home_html(host, [instance])

    assert "Work Special" in rendered
    assert "Control Plane" in rendered
    assert "cp.kris.openbrand.com" in rendered
    assert "https://cp.kris.openbrand.com/" in rendered
    assert "work-special.home.arpa:8783" in rendered
    assert "work-special.tail94915.ts.net:8783" in rendered
    assert "192.168.2.147:8783" in rendered


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
    assert "https://dj.home.arpa/" in rendered
    assert "toy-box.home.arpa:8793" in rendered
    assert "192.168.2.146:8793" in rendered


def test_host_home_urls_use_norman_host_route() -> None:
    module = _load_sync_agent_console_template()

    urls = module.host_home_urls(module.HOSTS["norman"])

    assert urls[0] == (
        "norman.tail94915.ts.net",
        "https://norman.tail94915.ts.net/host/",
    )
    assert ("norman.home.arpa", "https://norman.home.arpa/host/") in urls
    assert ("norman.home.lollie.org", "https://norman.home.lollie.org/host/") in urls


def test_norman_frontdoor_caddy_serves_shortcuts_locally() -> None:
    module = _load_frontdoor_renderer()

    rendered = module.render_caddy()

    assert (
        "(norman_internal_tls) {\n"
        "    tls {\n"
        "        issuer internal {\n"
        "            lifetime 6d\n"
        "        }\n"
        "    }\n"
        "}"
    ) in rendered
    assert (
        "http://norman.home.arpa, http://norman.home.lollie.org {\n"
        "    redir https://{host}{uri} 308\n"
        "}"
    ) in rendered
    assert (
        "norman.home.arpa, norman.home.lollie.org {\n"
        "    import norman_internal_tls\n"
        "    import norman_frontdoor\n"
        "}"
    ) in rendered
    assert (
        "http://norman.tail94915.ts.net {\n" "    redir https://{host}{uri} 308\n" "}"
    ) in rendered
    assert (
        "norman.tail94915.ts.net {\n"
        "    import norman_internal_tls\n"
        "    import norman_frontdoor\n"
        "}"
    ) in rendered


def test_norman_frontdoor_caddy_allows_explicit_canonical_cert_paths() -> None:
    module = _load_frontdoor_renderer()

    rendered = module.render_caddy(
        canonical_cert="/etc/caddy/certs/norman.tail94915.ts.net.crt",
        canonical_key="/etc/caddy/certs/norman.tail94915.ts.net.key",
    )

    assert (
        "norman.tail94915.ts.net {\n"
        "    tls /etc/caddy/certs/norman.tail94915.ts.net.crt "
        "/etc/caddy/certs/norman.tail94915.ts.net.key\n"
        "    import norman_frontdoor\n"
        "}"
    ) in rendered


def test_bot_proxy_caddy_routes_forward_original_prefix() -> None:
    source = _bot_proxy_renderer_source()

    assert "header_up X-Forwarded-Prefix /bot/{slug}" in source


def test_bot_proxy_caddy_separates_public_work_hosts_from_internal_tls_hosts() -> None:
    source = _bot_proxy_renderer_source()

    assert "goldbook.kris.openbrand.com" in source
    assert "platinum.kris.openbrand.com" in source
    assert "keystone.kris.openbrand.com" in source
    assert "infra.kris.openbrand.com" in source
    assert "kpis.kris.openbrand.com" in source
    assert "dashboards.kris.openbrand.com" in source
    assert "mls.kris.openbrand.com" in source
    assert "publisher.kris.openbrand.com" in source
    assert "scout.kris.openbrand.com" in source
    assert '"dj": ("dj", "yt")' in source
    assert '"studio": ("studio", "camera-studio")' in source
    assert '"tv": ("tv",)' in source
    assert "def bot_host_groups" in source
    assert "def _alias_bot_host_groups" in source
    assert "WORK_BOT_KRIS_LOLLIE_SUFFIX" in source
    assert 'host.endswith(".kris.openbrand.com")' in source
    assert "BOT_PUBLIC_INTERNAL_TLS_NAMES" in source


def test_bot_proxy_caddy_uses_internal_tls_for_pending_public_work_aliases() -> None:
    module = _load_bot_proxy_renderer()

    rendered = module.render_hosts()

    assert "# compere" in rendered
    assert "keystone.kris.openbrand.com {\n    import norman_internal_tls" in rendered
    assert "infra.kris.openbrand.com {\n    import norman_internal_tls" in rendered
    assert "kpis.kris.openbrand.com {\n    import norman_internal_tls" in rendered
    assert "leadership.kris.openbrand.com {\n    import norman_internal_tls" in rendered
    assert "scout.kris.openbrand.com {\n    import norman_internal_tls" in rendered
    assert "dashboards.kris.openbrand.com {\n    import norman_internal_tls" in rendered
    assert "tmi.kris.openbrand.com {\n    import norman_internal_tls" in rendered
    assert (
        "cp.kris.openbrand.com, control.kris.openbrand.com {\n    import norman_internal_tls"
        not in rendered
    )
    assert (
        "goldbook.kris.openbrand.com {\n    import norman_internal_tls" not in rendered
    )
    assert (
        "platinum.kris.openbrand.com {\n    import norman_internal_tls" not in rendered
    )


def test_bot_proxy_caddy_ip_gates_knox_local_work_aliases() -> None:
    module = _load_bot_proxy_renderer()

    rendered = module.render_hosts()

    assert (
        "@knox_allowed remote_ip 127.0.0.1/32 ::1/128 192.168.2.1/32 "
        "192.168.2.136/32 100.78.41.73/32 192.168.2.137/32 100.112.62.71/32 "
        "192.168.2.140/32 100.109.202.7/32 192.168.2.141/32" in rendered
    )
    assert 'respond "forbidden" 403' in rendered
    assert (
        "keystone.kris.openbrand.com {\n"
        "    import norman_internal_tls\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "infra.kris.openbrand.com {\n"
        "    import norman_internal_tls\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert "control.kris.openbrand.com {\n    @knox_allowed remote_ip" not in rendered
    assert "cp.kris.openbrand.com {\n    @knox_allowed remote_ip" not in rendered
    assert "goldbook.kris.openbrand.com {\n    @knox_allowed remote_ip" not in rendered
    assert "platinum.kris.openbrand.com {\n    @knox_allowed remote_ip" not in rendered


def test_bot_proxy_caddy_redirects_work_shortcuts_to_canonical_hosts() -> None:
    module = _load_bot_proxy_renderer()

    rendered = module.render_hosts()

    assert (
        "keystone.home.arpa, compere.home.arpa {\n"
        "    import norman_internal_tls\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert "redir https://keystone.kris.openbrand.com{uri} 308" in rendered
    assert (
        "control.kris.openbrand.com {\n"
        "    redir https://cp.kris.openbrand.com{uri} 308"
    ) in rendered
    assert (
        "leadership.kris.openbrand.com {\n" "    import norman_internal_tls"
    ) in rendered
    assert "redir https://kpis.kris.openbrand.com{uri} 308" in rendered


def test_bot_proxy_caddy_redirects_work_kris_lollie_aliases() -> None:
    module = _load_bot_proxy_renderer()

    rendered = module.render_hosts()

    assert (
        "keystone.kris.lollie.org, compere.kris.lollie.org {\n"
        "    import norman_internal_tls\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "cp.kris.lollie.org, control.kris.lollie.org, controlplane.kris.lollie.org {\n"
        "    import norman_internal_tls\n"
        "    redir https://cp.kris.openbrand.com{uri} 308"
    ) in rendered
    assert (
        "dashboards.kris.lollie.org, tmi.kris.lollie.org {\n"
        "    import norman_internal_tls"
    ) in rendered
    assert "redir https://dashboards.kris.openbrand.com{uri} 308" in rendered


def test_bot_proxy_caddy_redirects_home_knox_lollie_aliases() -> None:
    module = _load_bot_proxy_renderer()

    rendered_hosts = module.render_hosts()
    rendered_dns = module.render_dns_json()

    assert (
        "housebot.knox.lollie.org {\n"
        "    import norman_internal_tls\n"
        "    redir https://housebot.home.arpa{uri} 308"
    ) in rendered_hosts
    assert (
        "autocamera.knox.lollie.org {\n"
        "    import norman_internal_tls\n"
        "    redir https://autocamera.home.arpa{uri} 308"
    ) in rendered_hosts
    assert (
        "theseus.knox.lollie.org {\n"
        "    import norman_internal_tls\n"
        "    redir https://theseus.home.arpa{uri} 308"
    ) in rendered_hosts
    assert '"housebot.knox.lollie.org": "192.168.2.241"' in rendered_dns
    assert '"autocamera.knox.lollie.org": "192.168.2.241"' in rendered_dns
    assert '"theseus.knox.lollie.org": "192.168.2.241"' in rendered_dns
    assert "glimpser.knox.lollie.org" not in rendered_hosts


def test_bot_proxy_dns_json_can_target_tailnet_frontdoor() -> None:
    module = _load_bot_proxy_renderer()

    rendered_dns = module.render_dns_json(frontdoor_address="100.103.34.17")

    assert '"norman.home.arpa": "100.103.34.17"' in rendered_dns
    assert "norman.tail94915.ts.net" not in rendered_dns
    assert '"housebot.home.arpa": "100.103.34.17"' in rendered_dns
    assert '"housebot.knox.lollie.org": "100.103.34.17"' in rendered_dns
    assert '"llm.home.arpa": "100.103.34.17"' in rendered_dns


def test_bot_proxy_caddy_exposes_local_llm_frontdoor() -> None:
    module = _load_bot_proxy_renderer()

    rendered_hosts = module.render_hosts()
    rendered_dns = module.render_dns_json()

    assert (
        "llm.home.arpa, llm.knox.lollie.org {\n"
        "    import norman_internal_tls\n"
        "    reverse_proxy 192.168.2.133:18151 192.168.2.150:18151 "
        "192.168.2.151:18151 {\n"
        "        lb_policy first\n"
        "        lb_try_duration 15s\n"
        "        lb_try_interval 250ms\n"
        "        fail_duration 20s\n"
        "        max_fails 1\n"
        "        health_uri /healthz\n"
        "        health_interval 3s\n"
        "        health_timeout 2s\n"
        "    }\n"
        "}"
    ) in rendered_hosts
    assert '"llm.knox.lollie.org": "192.168.2.241"' in rendered_dns
    assert '"llm.home.arpa": "192.168.2.241"' in rendered_dns


def test_bot_proxy_caddy_exposes_subprime_lane_aliases() -> None:
    module = _load_bot_proxy_renderer()

    rendered_paths = module.render_paths()
    rendered_hosts = module.render_hosts()

    assert "# subprime" in rendered_paths
    assert "redir /bot/subprime /bot/subprime/ 308" in rendered_paths
    assert "reverse_proxy 192.168.2.241:8796" in rendered_paths

    assert "# subprime" in rendered_hosts
    assert "subprime.home.arpa" in rendered_hosts
    assert "subprime.norman.home.arpa" in rendered_hosts
    assert "botprime.home.arpa" in rendered_hosts
    assert "bot.norman.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.2.241:8796" in rendered_hosts


def test_bot_proxy_caddy_exposes_ops_lane_aliases() -> None:
    module = _load_bot_proxy_renderer()

    rendered_paths = module.render_paths()
    rendered_hosts = module.render_hosts()
    rendered_dns = module.render_dns_json()

    assert "# ops" in rendered_paths
    assert "redir /bot/ops /bot/ops/ 308" in rendered_paths
    assert "reverse_proxy 192.168.2.241:8797" in rendered_paths

    assert "# ops" in rendered_hosts
    assert "ops.home.arpa" in rendered_hosts
    assert "ops.norman.home.arpa" in rendered_hosts
    assert "normanops.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.2.241:8797" in rendered_hosts
    assert '"ops.home.arpa": "192.168.2.241"' in rendered_dns


def test_bot_proxy_caddy_exposes_switchboard_aliases() -> None:
    module = _load_bot_proxy_renderer()

    rendered_hosts = module.render_hosts()
    rendered_dns = module.render_dns_json()

    assert "# switchboard" in rendered_hosts
    assert "switchboard.home.arpa" in rendered_hosts
    assert "switchboard.norman.home.arpa" in rendered_hosts
    assert "reverse_proxy 127.0.0.1:8000" in rendered_hosts
    assert (
        "reverse_proxy 192.168.2.241:8796"
        not in rendered_hosts.split("# switchboard", 1)[1]
    )
    assert '"switchboard.home.arpa": "192.168.2.241"' in rendered_dns


def test_directory_shortcuts_prefer_public_work_bot_hosts() -> None:
    home_source = _home_js_source()
    systems_source = _systems_js_source()

    for source in (home_source, systems_source):
        assert "dj.home.arpa" in source
        assert "tv.home.arpa" in source
        assert "studio.home.arpa" in source
        assert "goldbook.kris.openbrand.com" in source
        assert "platinum.kris.openbrand.com" in source
        assert "keystone.kris.openbrand.com" in source
        assert "infra.kris.openbrand.com" in source
        assert "kpis.kris.openbrand.com" in source
        assert "dashboards.kris.openbrand.com" in source
        assert "mls.kris.openbrand.com" in source
        assert "scout.kris.openbrand.com" in source
        assert "publisher.kris.openbrand.com" in source


def test_bbs_directory_cards_render_agent_marks() -> None:
    home_source = _home_js_source()
    systems_source = _systems_js_source()
    styles_source = _styles_source()
    base_source = _base_template_source()

    for source in (home_source, systems_source):
        assert "function fleetMarkForLabel(" in source
        assert "function fleetMarkForService(" in source
        assert 'class="fleet-card__mark"' in source
        assert 'class="fleet-card__identity"' in source
        assert 'class="fleet-card__eyebrow"' in source
        assert 'data-tone="${escapeHtml(tone)}"' in source
        assert "housebot: 'HB'" in source
        assert "'control plane': 'CP'" in source
        assert "'leadership kpis': 'LK'" in source

    assert ".fleet-card__identity" in styles_source
    assert ".fleet-card__identity::after" in styles_source
    assert ".fleet-card__eyebrow" in styles_source
    assert '.fleet-card__mark[data-tone="norman"]' in styles_source
    assert '.fleet-card__mark[data-tone="private"]' in styles_source
    assert '.fleet-card__mark[data-tone="work"]' in styles_source
    assert (
        '--fleet-plate-font: "Poppins", "Space Grotesk", sans-serif;' in styles_source
    )
    assert '--fleet-plate-font: "Fraunces", "Space Grotesk", serif;' in styles_source
    assert "family=Poppins" in base_source
    assert "family=Fraunces" in base_source


def test_sync_template_prefers_public_work_console_url() -> None:
    module = _load_sync_agent_console_template()

    instance = module.ConsoleInstance(
        name="control-plane",
        host_name="work-special",
        ssh_target="root@192.168.2.147",
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
        codex_home="/home/kristopher/.codex-control-plane",
    )

    assert module.instance_public_host(instance) == "cp.kris.openbrand.com"
    assert module.instance_console_urls(instance)["url"] == (
        "https://cp.kris.openbrand.com/?token=demo-token&profile={profile}"
    )


def test_sync_template_uses_new_work_alias_canonicals() -> None:
    module = _load_sync_agent_console_template()

    for name, expected in (
        ("compere", "keystone.kris.openbrand.com"),
        ("earlybird", "earlybird.kris.openbrand.com"),
        ("infra", "infra.kris.openbrand.com"),
        ("leadership-kpis", "kpis.kris.openbrand.com"),
        ("market-sizing", "market.kris.openbrand.com"),
        ("mls", "mls.kris.openbrand.com"),
        ("panelbot", "panelbot.kris.openbrand.com"),
        ("publisher", "publisher.kris.openbrand.com"),
        ("scout", "scout.kris.openbrand.com"),
        ("tmi-dashboards", "dashboards.kris.openbrand.com"),
    ):
        instance = module.ConsoleInstance(
            name=name,
            host_name="work-special",
            ssh_target="root@192.168.2.147",
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
            codex_home=f"/home/kristopher/.codex-{name}",
        )
        assert module.instance_public_host(instance) == expected


def test_sync_template_uses_home_bot_alias_canonicals() -> None:
    module = _load_sync_agent_console_template()

    for name, expected, host_name in (
        ("autocamera", "autocamera.home.arpa", "hal"),
        ("cloudagent", "cloudagent.home.arpa", "networking-host"),
        ("housebot", "housebot.home.arpa", "toy-box"),
        ("networking", "networking.home.arpa", "networking-host"),
        ("phone-ops", "phone.home.arpa", "toy-box"),
        ("theseus", "theseus.home.arpa", "hal"),
        ("uplink", "uplink.home.arpa", "networking-host"),
    ):
        instance = module.ConsoleInstance(
            name=name,
            host_name=host_name,
            ssh_target=module.HOSTS[host_name].ssh_target,
            use_sudo=module.HOSTS[host_name].use_sudo,
            env_file=f"/etc/{name}/codex-web.env",
            web_path=f"/usr/local/lib/{name}/web.py",
            launch_path=f"/usr/local/lib/{name}/launch.sh",
            supervisor_path=f"/usr/local/lib/{name}/supervisor.sh",
            restart_units=(f"{name}-codex.service", f"{name}-codex-web.service"),
            agent_label=name.title(),
            web_port="8780",
            web_token="demo-token",
            prompt_file=f"/etc/{name}/codex-system-prompt.txt",
            codex_home=f"/home/kristopher/.codex-{name}",
        )
        assert module.instance_public_host(instance) == expected


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


def test_sync_template_keeps_model_upgrades_operator_triggered() -> None:
    source = _sync_agent_console_template_source()

    assert "--set-codex-model" in source
    assert '"HOUSEBOT_CODEX_MODEL": clean_model' in source
    assert (
        "sync_instance_model_setting(\n                host, instance, args.set_codex_model"
        in source
    )
    assert "if args.set_codex_model and sync_instance_model_setting" in source
    assert '"HOUSEBOT_CODEX_ENV_FILE": instance.env_file' in source
    assert "for attempt in $(seq 1 20)" in source


def test_sync_template_rolls_runtime_bridge_through_norman_keys() -> None:
    source = _sync_agent_console_template_source()

    assert 'RUNTIME_BRIDGE_TOKEN_SECRET = "norman/console-runtime-token"' in source
    assert "def runtime_bridge_settings_from_references(" in source
    assert "def sync_instance_runtime_bridge_settings(" in source
    assert 'RUNTIME_BRIDGE_SECRET_LANE = "shared_infra"' in source
    assert 'RUNTIME_BRIDGE_JOB_CREATE_TIMEOUT_SECONDS = "15"' in source
    assert 'RUNTIME_BRIDGE_TOKEN_RETRY_SECONDS = "30"' in source
    assert 'RUNTIME_BRIDGE_PROOF_TTL_SECONDS = "120"' in source
    assert 'RUNTIME_BRIDGE_STARTUP_JITTER_SECONDS = "45"' in source
    assert 'RUNTIME_BRIDGE_ROUTE_OUTCOME_LIMIT = "200"' in source
    assert 'RUNTIME_BRIDGE_LOCAL_FIRST_PROOF_LIMIT = "250"' in source
    assert '"NORMAN_CONSOLE_RUNTIME_API_BASE": api_base' in source
    assert '"NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET": token_secret' in source
    assert '"NORMAN_KEYS_URL": keys_url' in source
    assert '"NORMAN_KEYS_TOKEN": keys_token' in source
    assert '"NORMAN_CONSOLE_RUNTIME_PROOF_TTL_SECONDS": (' in source
    assert '"NORMAN_CONSOLE_RUNTIME_JOB_CREATE_TIMEOUT_SECONDS": (' in source
    assert '"NORMAN_CONSOLE_RUNTIME_TOKEN_RETRY_SECONDS": (' in source
    assert '"NORMAN_CONSOLE_RUNTIME_STARTUP_JITTER_SECONDS": (' in source
    assert '"NORMAN_CONSOLE_RUNTIME_LOCAL_FIRST_PROOF_LIMIT": (' in source
    assert '"NORMAN_CONSOLE_RUNTIME_TOKEN":' not in source
    assert '"NORMAN_API_TOKEN":' not in source


def test_sync_template_rolls_kernel_primary_to_canary_instances() -> None:
    source = _sync_agent_console_template_source()
    module = _load_sync_agent_console_template()

    assert "KERNEL_PRIMARY_CANARY_INSTANCES: tuple[str, ...] = (" in source
    assert '"cloudagent"' in source
    assert '"housebot"' in source
    assert '"networking"' in source
    assert '"scout"' in source
    assert '"uplink"' in source
    assert '"norman"' in source
    assert "KERNEL_OWNED_TURN_CANARY_INSTANCES: tuple[str, ...] = (" in source
    assert "def kernel_rollout_settings_for_instance(" in source
    assert "def sync_instance_kernel_rollout_settings(" in source
    assert "sync_instance_kernel_rollout_settings(host, instance)" in source
    assert '"NORMAN_LOCAL_LLM_CALL_TIMEOUT_SECONDS": "360"' in source
    assert '"NORMAN_LOCAL_LLM_FOREGROUND_TIMEOUT_SECONDS": "240"' in source
    assert '"NORMAN_LOCAL_LLM_SHORT_TIMEOUT_SECONDS": "120"' in source
    assert '"NORMAN_LOCAL_LLM_QUICK_MAX_OUTPUT_TOKENS": "384"' in source
    assert '"NORMAN_LOCAL_LLM_SHORT_MAX_OUTPUT_TOKENS": "800"' in source
    assert '"NORMAN_LOCAL_LLM_NUM_CTX": "8192"' in source
    assert '"NORMAN_LOCAL_LLM_SHORT_NUM_CTX": "4096"' in source
    assert '"NORMAN_LOCAL_LLM_FALLBACK_MODELS": ""' in source
    assert '"NORMAN_LOCAL_LLM_ALLOW_TINY_FOREGROUND_FALLBACK": "0"' in source

    housebot = module.ConsoleInstance(
        name="housebot",
        host_name="toy-box",
        ssh_target=module.HOSTS["toy-box"].ssh_target,
        use_sudo=module.HOSTS["toy-box"].use_sudo,
        env_file="/etc/housebot/codex-web.env",
        web_path="/opt/housebot/scripts/housebot_codex_web.py",
        launch_path="/opt/housebot/scripts/housebot_codex_launch.sh",
        supervisor_path="/opt/housebot/scripts/housebot_codex_supervisor.sh",
        restart_units=("housebot-codex.service", "housebot-codex-web.service"),
        agent_label="Housebot",
        web_port="8789",
        web_token="demo-token",
        prompt_file="/etc/housebot/codex-system-prompt.txt",
        codex_home="/root/.codex-housebot",
    )
    control_plane = module.ConsoleInstance(
        name="control-plane",
        host_name="work-special",
        ssh_target=module.HOSTS["work-special"].ssh_target,
        use_sudo=module.HOSTS["work-special"].use_sudo,
        env_file="/etc/control-plane/codex-web.env",
        web_path="/home/kristopher/code/control_plane/scripts/control_plane_codex_web.py",
        launch_path="/home/kristopher/code/control_plane/scripts/control_plane_codex_launch.sh",
        supervisor_path="/home/kristopher/code/control_plane/scripts/control_plane_codex_supervisor.sh",
        restart_units=(
            "control-plane-codex.service",
            "control-plane-codex-web.service",
        ),
        agent_label="Control Plane",
        web_port="8782",
        web_token="demo-token",
        prompt_file="/etc/control-plane/codex-system-prompt.txt",
        codex_home="/home/kristopher/.codex-control-plane",
    )

    canary_settings = module.kernel_rollout_settings_for_instance(housebot)
    shadow_settings = module.kernel_rollout_settings_for_instance(control_plane)

    assert canary_settings["NORMAN_TUI_BACKEND"] == "kernel"
    assert canary_settings["NORMAN_TUI_KERNEL_EXECUTION"] == "1"
    assert canary_settings["NORMAN_TUI_KERNEL_PRIMARY"] == "1"
    assert canary_settings["NORMAN_TUI_KERNEL_OWNED_TURN"] == "1"
    assert canary_settings["NORMAN_TUI_KERNEL_PRIMARY_STRICT"] == "0"
    assert canary_settings["NORMAN_TUI_KERNEL_CLOUD_FALLBACK"] == "1"
    assert canary_settings["NORMAN_TUI_KERNEL_WORKSPACE_PREFLIGHT"] == "1"
    assert canary_settings["NORMAN_TUI_KERNEL_PRIMARY_MAX_STEPS"] == "5"
    assert shadow_settings["NORMAN_TUI_BACKEND"] == "kernel-shadow"
    assert shadow_settings["NORMAN_TUI_KERNEL_EXECUTION"] == "0"
    assert shadow_settings["NORMAN_TUI_KERNEL_PRIMARY"] == "0"
    assert shadow_settings["NORMAN_TUI_KERNEL_OWNED_TURN"] == "0"
    assert shadow_settings["NORMAN_TUI_KERNEL_CLOUD_FALLBACK"] == "0"

    for name in ("cloudagent", "networking", "norman", "scout", "uplink"):
        promoted = module.ConsoleInstance(
            name=name,
            host_name=(
                "networking-host"
                if name in {"cloudagent", "networking", "uplink"}
                else "norman"
            ),
            ssh_target="test-host",
            use_sudo=True,
            env_file=f"/etc/{name}/codex-web.env",
            web_path=f"/opt/{name}/codex_web.py",
            launch_path=f"/opt/{name}/codex_launch.sh",
            supervisor_path=f"/opt/{name}/codex_supervisor.sh",
            restart_units=(f"{name}-codex.service", f"{name}-codex-web.service"),
            agent_label=name.title(),
            web_port="8788",
            web_token="demo-token",
            prompt_file=f"/etc/{name}/codex-system-prompt.txt",
            codex_home=f"/tmp/{name}",
        )
        settings = module.kernel_rollout_settings_for_instance(promoted)
        assert settings["NORMAN_TUI_BACKEND"] == "kernel"
        assert settings["NORMAN_TUI_KERNEL_EXECUTION"] == "1"
        assert settings["NORMAN_TUI_KERNEL_OWNED_TURN"] == "1"
        assert settings["NORMAN_TUI_KERNEL_PRIMARY_STRICT"] == "0"
        assert settings["NORMAN_TUI_KERNEL_CLOUD_FALLBACK"] == "1"


def test_runtime_bridge_settings_prefers_broker_reference(monkeypatch) -> None:
    module = _load_sync_agent_console_template()
    instance = module.ConsoleInstance(
        name="uplink",
        host_name="networking-host",
        ssh_target=module.HOSTS["networking-host"].ssh_target,
        use_sudo=module.HOSTS["networking-host"].use_sudo,
        env_file="/etc/net-agents/uplink.env",
        web_path="/home/debian/networking/scripts/uplink_codex_web.py",
        launch_path="/home/debian/networking/scripts/uplink_codex_launch.sh",
        supervisor_path="/home/debian/networking/scripts/uplink_codex_supervisor.sh",
        restart_units=("uplink-codex.service", "uplink-codex-web.service"),
        agent_label="Uplink",
        web_port="8792",
        web_token="demo-token",
        prompt_file="/etc/net-agents/uplink-prompt.txt",
        codex_home="/home/debian/.codex-uplink",
    )

    def fake_read_env(_host, _instance, keys):
        assert "NORMAN_CONSOLE_RUNTIME_TOKEN" not in keys
        return {
            "NORMAN_CONSOLE_RUNTIME_API_BASE": (
                "http://192.168.2.241:8000/api/v1/console-runtime"
            ),
            "NORMAN_KEYS_URL": "http://192.168.2.241:8000",
            "NORMAN_KEYS_TOKEN": "keys-token",
            "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET": "norman/console-runtime-token",
        }

    monkeypatch.setattr(module, "read_instance_env_values", fake_read_env)

    settings = module.runtime_bridge_settings_from_references({"uplink": instance})

    assert settings["NORMAN_CONSOLE_RUNTIME_API_BASE"] == (
        "http://192.168.2.241:8000/api/v1/console-runtime"
    )
    assert settings["NORMAN_KEYS_URL"] == "http://192.168.2.241:8000"
    assert settings["NORMAN_KEYS_TOKEN"] == "keys-token"
    assert (
        settings["NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET"]
        == "norman/console-runtime-token"
    )
    assert settings["NORMAN_CONSOLE_RUNTIME_ENABLED"] == "1"
    assert settings["NORMAN_CONSOLE_RUNTIME_LANE"] == "shared_infra"
    assert settings["NORMAN_CONSOLE_RUNTIME_JOB_CREATE_TIMEOUT_SECONDS"] == "15"
    assert settings["NORMAN_CONSOLE_RUNTIME_TOKEN_RETRY_SECONDS"] == "30"
    assert settings["NORMAN_CONSOLE_RUNTIME_PROOF_TTL_SECONDS"] == "120"
    assert settings["NORMAN_CONSOLE_RUNTIME_STARTUP_JITTER_SECONDS"] == "45"
    assert settings["NORMAN_CONSOLE_RUNTIME_ROUTE_OUTCOME_LIMIT"] == "200"
    assert settings["NORMAN_CONSOLE_RUNTIME_LOCAL_FIRST_PROOF_LIMIT"] == "250"
    assert "NORMAN_CONSOLE_RUNTIME_TOKEN" not in settings
    assert "NORMAN_API_TOKEN" not in settings


def test_runtime_bridge_sync_writes_broker_env_without_direct_token(
    monkeypatch,
) -> None:
    module = _load_sync_agent_console_template()
    instance = module.ConsoleInstance(
        name="scout",
        host_name="work-special",
        ssh_target=module.HOSTS["work-special"].ssh_target,
        use_sudo=module.HOSTS["work-special"].use_sudo,
        env_file="/etc/scout/codex-web.env",
        web_path="/usr/local/lib/scout/scout_codex_web.py",
        launch_path="/usr/local/lib/scout/scout_codex_launch.sh",
        supervisor_path="/usr/local/lib/scout/scout_codex_supervisor.sh",
        restart_units=("scout-codex.service", "scout-codex-web.service"),
        agent_label="Ranger",
        web_port="8793",
        web_token="demo-token",
        prompt_file="/etc/scout/codex-system-prompt.txt",
        codex_home="/home/kristopher/.codex-scout",
    )
    captured: list[list[str]] = []

    def fake_capture(cmd):
        captured.append(cmd)
        return "changed"

    monkeypatch.setattr(module, "capture", fake_capture)

    changed = module.sync_instance_runtime_bridge_settings(
        module.HOSTS["work-special"],
        instance,
        {
            "NORMAN_CONSOLE_RUNTIME_ENABLED": "1",
            "NORMAN_CONSOLE_RUNTIME_API_BASE": (
                "http://192.168.2.241:8000/api/v1/console-runtime"
            ),
            "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET": "norman/console-runtime-token",
            "NORMAN_KEYS_URL": "http://192.168.2.241:8000",
            "NORMAN_KEYS_TOKEN": "keys-token",
        },
    )

    assert changed is True
    rendered_command = " ".join(captured[0])
    assert "NORMAN_KEYS_TOKEN" in rendered_command
    assert "NORMAN_CONSOLE_RUNTIME_TOKEN_SECRET" in rendered_command
    assert "remove_keys = json.loads" in rendered_command
    assert "for key in remove_keys" in rendered_command
    for key in module.RUNTIME_BRIDGE_LEGACY_TOKEN_KEYS:
        assert key in rendered_command
    assert '"NORMAN_CONSOLE_RUNTIME_TOKEN":' not in rendered_command
    assert '"NORMAN_API_TOKEN":' not in rendered_command


def test_kernel_rollout_sync_writes_backend_env(monkeypatch) -> None:
    module = _load_sync_agent_console_template()
    instance = module.ConsoleInstance(
        name="uplink",
        host_name="networking-host",
        ssh_target=module.HOSTS["networking-host"].ssh_target,
        use_sudo=module.HOSTS["networking-host"].use_sudo,
        env_file="/etc/net-agents/uplink.env",
        web_path="/home/debian/networking/radio/phobos_hunt/scripts/uplink_codex_web.py",
        launch_path="/home/debian/networking/radio/phobos_hunt/scripts/uplink_codex_launch.sh",
        supervisor_path="/home/debian/networking/radio/phobos_hunt/scripts/uplink_codex_supervisor.sh",
        restart_units=("uplink-codex.service", "uplink-codex-web.service"),
        agent_label="Uplink",
        web_port="8792",
        web_token="demo-token",
        prompt_file="/etc/net-agents/uplink-prompt.txt",
        codex_home="/home/debian/.codex-uplink",
    )
    captured: list[list[str]] = []

    def fake_capture(cmd):
        captured.append(cmd)
        return "changed"

    monkeypatch.setattr(module, "capture", fake_capture)

    changed = module.sync_instance_kernel_rollout_settings(
        module.HOSTS["networking-host"],
        instance,
    )

    assert changed is True
    rendered_command = " ".join(captured[0])
    assert "NORMAN_TUI_BACKEND" in rendered_command
    assert "NORMAN_TUI_KERNEL_EXECUTION" in rendered_command
    assert "NORMAN_TUI_KERNEL_PRIMARY" in rendered_command


def test_local_sync_systemd_units_target_hal() -> None:
    service = _systemd_unit_source("norman-agent-console-sync-local.service")
    path = _systemd_unit_source("norman-agent-console-sync-local.path")
    timer = _systemd_unit_source("norman-agent-console-sync-local.timer")

    assert "sync_agent_console_template.py --targets hal" in service
    assert (
        "/home/kristopher/code/norman/scripts/agent_console_template/agent_console_web.py"
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
    old_proxy = os.environ.get("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "cp.kris.openbrand.com"
        os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = "1"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "cp.kris.openbrand.com,work-special.home.arpa,192.168.2.147"
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
        if old_proxy is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = old_proxy

    assert module.canonical_origin_components() == (
        "https",
        "cp.kris.openbrand.com",
    )


def test_canonical_origin_uses_http_for_home_arpa_hosts() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    old_proxy = os.environ.get("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "work-special.home.arpa"
        os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = "0"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "work-special.home.arpa,192.168.2.147"
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
        if old_proxy is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = old_proxy

    assert module.canonical_origin_components() == (
        "http",
        f"work-special.home.arpa:{module.PORT}",
    )


def test_canonical_origin_uses_https_for_frontdoor_home_arpa_hosts() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    old_proxy = os.environ.get("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "dj.home.arpa"
        os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = "1"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "dj.home.arpa,toy-box.home.arpa,192.168.2.146"
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
        if old_proxy is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = old_proxy

    assert module.canonical_origin_components() == (
        "https",
        "dj.home.arpa",
    )


def test_should_not_redirect_canonical_from_lan_alias_to_public_host() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    old_proxy = os.environ.get("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY")
    old_token = os.environ.get("HOUSEBOT_CODEX_WEB_TOKEN")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "cp.kris.openbrand.com"
        os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = "1"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "work-special.home.arpa,192.168.2.147"
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
        if old_proxy is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = old_proxy
        if old_token is None:
            os.environ.pop("HOUSEBOT_CODEX_WEB_TOKEN", None)
        else:
            os.environ["HOUSEBOT_CODEX_WEB_TOKEN"] = old_token

    handler = object.__new__(module.Handler)
    handler.headers = {"Host": "work-special.home.arpa:8783"}
    handler.client_address = ("192.168.2.50", 12345)

    parsed = module.urlparse("http://work-special.home.arpa:8783/?profile=slate")

    assert (
        module.Handler.should_redirect_canonical(
            handler,
            parsed,
            {"profile": ["slate"]},
        )
        is False
    )


def test_should_not_redirect_canonical_from_private_ip_to_public_host() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    old_proxy = os.environ.get("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "cp.kris.openbrand.com"
        os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = "1"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "work-special.home.arpa,192.168.2.147"
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
        if old_proxy is None:
            os.environ.pop("HOUSEBOT_CODEX_CANONICAL_VIA_PROXY", None)
        else:
            os.environ["HOUSEBOT_CODEX_CANONICAL_VIA_PROXY"] = old_proxy

    handler = object.__new__(module.Handler)
    handler.headers = {"Host": "192.168.2.147:8783"}
    handler.client_address = ("192.168.2.50", 12345)

    parsed = module.urlparse("http://192.168.2.147:8783/?profile=slate")

    assert (
        module.Handler.should_redirect_canonical(
            handler,
            parsed,
            {"profile": ["slate"]},
        )
        is False
    )


def test_build_norman_prime_href_preserves_request_host_family() -> None:
    module = _load_agent_console_web()

    assert (
        module.build_norman_prime_href("192.168.2.137") == "http://192.168.2.241:8000/"
    )
    assert (
        module.build_norman_prime_href("switchboard.tail94915.ts.net")
        == "https://norman.tail94915.ts.net/"
    )
    assert (
        module.build_norman_prime_href("uplink.home.arpa")
        == "https://norman.home.arpa/"
    )


def test_render_console_link_url_keeps_sibling_service_hostnames() -> None:
    old_host = os.environ.get("HOUSEBOT_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("HOUSEBOT_CODEX_LOCAL_HOST_ALIASES")
    old_port = os.environ.get("HOUSEBOT_CODEX_WEB_PORT")
    try:
        os.environ["HOUSEBOT_CODEX_CANONICAL_HOST"] = "dj.home.arpa"
        os.environ["HOUSEBOT_CODEX_LOCAL_HOST_ALIASES"] = (
            "dj.home.arpa,toy-box.home.arpa,192.168.2.146"
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
            "lan_url": "http://192.168.2.146:8793/?token={token}&profile={profile}",
        },
        token="demo-token",
        profile="slate",
        request_host="dj.home.arpa",
        route_mode="host",
    )
    sibling_service = module.render_console_link_url(
        {
            "url": "http://toy-box.home.arpa:8787/?token={token}&profile={profile}",
            "lan_url": "http://192.168.2.146:8787/?token={token}&profile={profile}",
        },
        token="demo-token",
        profile="slate",
        request_host="dj.home.arpa",
        route_mode="host",
    )

    assert same_service.startswith("http://dj.home.arpa:8793/")
    assert sibling_service.startswith("http://toy-box.home.arpa:8787/")


def test_codex_account_capacity_parser_and_forecast_are_aggregate_only() -> None:
    module = _load_agent_console_web()
    observed_at = 1_789_000_000

    parsed = module.parse_codex_account_capacity_pane(
        """
        5h limit: 84% left · resets in 2h 30m
        Weekly limit: 63% remaining · resets in 6d 4h
        """,
        observed_at=observed_at,
        auth_mode="chatgpt",
    )
    forecast = module.codex_account_capacity_forecast(
        [
            module.normalize_usage_entry(
                {
                    "started_at": observed_at - 7200,
                    "finished_at": observed_at - 3600,
                    "success": True,
                    "runtime": "codex",
                    "provider_surface": "openai-direct",
                    "codex_auth_mode": "chatgpt",
                    "total_tokens": 1200,
                }
            )
        ],
        now=observed_at,
        windows=parsed["windows"],
    )

    assert parsed["source"] == "interactive_usage"
    assert parsed["state"] == "available"
    assert parsed["minimum_window_percent_left"] == 63
    assert parsed["windows"][0]["label"] == "Short window"
    assert parsed["windows"][0]["reset_seconds"] == 9000
    assert parsed["windows"][1]["label"] == "Weekly"
    assert forecast["tokens_per_hour"] > 0
    assert forecast["earliest_reset_seconds"] == 9000
    assert forecast["capacity_credit_equivalent_unknown"] is True
    assert "limit:" not in json.dumps(parsed)


def test_codex_account_capacity_forecast_excludes_api_and_bedrock_usage() -> None:
    module = _load_agent_console_web()
    observed_at = 1_789_000_000
    entries = [
        module.normalize_usage_entry(
            {
                "started_at": observed_at - 3600,
                "finished_at": observed_at - 1800,
                "success": True,
                "runtime": "codex",
                "provider_surface": "openai-direct",
                "codex_auth_mode": "chatgpt",
                "total_tokens": 1200,
            }
        ),
        module.normalize_usage_entry(
            {
                "started_at": observed_at - 3600,
                "finished_at": observed_at - 1800,
                "success": True,
                "runtime": "codex",
                "provider_surface": "openai-direct",
                "codex_auth_mode": "api_key",
                "total_tokens": 34_000,
            }
        ),
        module.normalize_usage_entry(
            {
                "started_at": observed_at - 3600,
                "finished_at": observed_at - 1800,
                "success": True,
                "runtime": "codex",
                "provider_surface": "aws-bedrock",
                "total_tokens": 56_000,
            }
        ),
    ]

    forecast = module.codex_account_capacity_forecast(
        entries,
        now=observed_at,
        windows=[{"reset_seconds": 7200}],
    )

    assert entries[0]["charge_ledger_kind"] == "chatgpt_codex_credit_estimate"
    assert entries[1]["charge_ledger_kind"] == "api_rate_card_estimate"
    assert forecast["sample_count"] == 1
    assert forecast["usage_window_tokens"] == 1200
    assert forecast["subscription_usage_window_tokens"] == 1200
    assert forecast["projected_tokens_to_earliest_reset"] == 4800


def test_codex_account_capacity_invalidates_on_auth_mode_change(
    tmp_path: Path,
) -> None:
    module = _load_agent_console_web()
    module.CODEX_ACCOUNT_CAPACITY_PATH = tmp_path / "capacity.json"
    module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH = tmp_path / "capacity.jsonl"
    observed_at = module.now_ts()
    module._persist_codex_account_capacity(
        {
            **module.default_codex_account_capacity(),
            "source": "interactive_usage",
            "observed_at": observed_at,
            "last_probe_at": observed_at,
            "auth_mode": "api_key",
            "state": "available",
            "windows": [{"label": "Current", "percent_left": 84}],
        }
    )

    snapshot = module.codex_account_capacity_snapshot(auth_mode="chatgpt")

    assert snapshot["auth_mode"] == "chatgpt"
    assert snapshot["state"] == "unknown"
    assert snapshot["fresh"] is False
    assert snapshot["eligible_for_subscription_route"] is False


def test_codex_account_capacity_parser_marks_limit_and_unknown_safely() -> None:
    module = _load_agent_console_web()

    blocked = module.parse_codex_account_capacity_pane(
        "You've hit your usage limit. Try again at 5:28 PM.",
        observed_at=1_789_000_000,
        auth_mode="chatgpt",
    )

    assert blocked["state"] == "blocked"
    assert blocked["windows"] == []
    fresh = module.parse_codex_account_capacity_pane(
        """
        You've hit your usage limit. Try again at 5:28 PM.
        5h limit: 84% left · resets in 2h
        """,
        observed_at=1_789_000_000,
        auth_mode="chatgpt",
    )
    assert fresh["state"] == "available"
    assert fresh["minimum_window_percent_left"] == 84
    assert module.parse_codex_account_capacity_pane("normal terminal output") == {}


def test_codex_account_capacity_parser_normalizes_percent_used_without_pane_text() -> (
    None
):
    module = _load_agent_console_web()

    parsed = module.parse_codex_account_capacity_pane(
        """
        5h limit: 16% used · resets in 2h
        Weekly limit: 40% consumed · resets in 6d
        """
    )

    assert parsed["state"] == "available"
    assert [item["percent_left"] for item in parsed["windows"]] == [84, 60]
    assert "used" not in json.dumps(parsed)
    assert "consumed" not in json.dumps(parsed)


def test_codex_account_capacity_probe_requires_changed_pane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_agent_console_web()
    module.CODEX_ACCOUNT_CAPACITY_PROBE_POLL_SECONDS = 0.01
    prompt_pane = "OpenAI Codex (v0.144.5)\n\n› "
    panes = iter(
        [
            prompt_pane,
            "5h limit: 84% left · resets in 2h\n\n› ",
        ]
    )
    sent: list[str] = []
    monkeypatch.setattr(module, "capture_pane", lambda: next(panes))
    monkeypatch.setattr(module, "send_text", lambda value: sent.append(value))

    payload = module._capture_codex_account_capacity_command(
        "/usage",
        observed_at=1_789_000_000,
        auth_mode="chatgpt",
        baseline_pane=prompt_pane,
    )

    assert sent == ["/usage"]
    assert payload["state"] == "available"
    assert payload["minimum_window_percent_left"] == 84


def test_codex_subscription_capacity_prefers_flex_only_for_fresh_personal_bedrock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NORMAN_CODEX_STANDARD_PROFILE_V2", "personal-bedrock")
    monkeypatch.setenv("NORMAN_CODEX_STANDARD_AWS_PROFILE", "norman-bedrock")
    monkeypatch.setenv("NORMAN_CODEX_AGENT_GROUP", "personal")
    monkeypatch.setenv("NORMAN_CODEX_BILLING_OWNER", "kristopher")
    module = _load_agent_console_web()
    monkeypatch.setattr(module, "stored_codex_auth_mode", lambda: "chatgpt")
    module.CODEX_ACCOUNT_CAPACITY_PATH = tmp_path / "capacity.json"
    module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH = tmp_path / "capacity.jsonl"
    observed_at = module.now_ts()
    capacity = module.default_codex_account_capacity()
    capacity.update(
        {
            "source": "interactive_usage",
            "observed_at": observed_at,
            "last_probe_at": observed_at,
            "auth_mode": "chatgpt",
            "state": "available",
            "windows": [
                {
                    "label": "Short window",
                    "percent_left": 84,
                    "reset_hint": "2h",
                    "reset_seconds": 7200,
                }
            ],
        }
    )
    module._persist_codex_account_capacity(capacity)
    snapshot = module.codex_account_capacity_snapshot(auth_mode="chatgpt")

    decision = module.codex_subscription_capacity_route_decision(
        runtime="codex",
        model=module.MODEL,
        service_tier="default",
        capacity=snapshot,
    )

    assert snapshot["eligible_for_subscription_route"] is True
    assert decision["selected"] is True
    assert decision["selected_service_tier"] == "flex"
    assert (
        module.codex_subscription_capacity_route_decision(
            runtime="codex",
            model=module.MODEL,
            service_tier="default",
            route_lock=True,
            capacity=snapshot,
        )["selected"]
        is False
    )
    monkeypatch.setattr(module, "stored_codex_auth_mode", lambda: "api_key")
    assert (
        module.codex_subscription_capacity_route_decision(
            runtime="codex",
            model=module.MODEL,
            service_tier="default",
            capacity=snapshot,
        )["selected"]
        is False
    )
    assert (
        module.codex_subscription_capacity_route_decision(
            runtime="codex",
            model=module.MODEL,
            service_tier="default",
            service_tier_recovery={"service_tier": "default"},
            capacity=snapshot,
        )["selected"]
        is False
    )


def test_codex_account_capacity_probe_only_runs_at_idle_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_agent_console_web()
    module.CODEX_ACCOUNT_CAPACITY_PATH = tmp_path / "capacity.json"
    module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH = tmp_path / "capacity.jsonl"
    module.CODEX_ACCOUNT_CAPACITY_PROBE_POLL_SECONDS = 0.01
    module.CODEX_ACCOUNT_CAPACITY_PROBE_THREAD = None
    monkeypatch.setattr(module, "stored_codex_auth_mode", lambda: "chatgpt")
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(module, "prompt_thread_alive", lambda: False)
    prompt_pane = "OpenAI Codex (v0.118.0)\n\n› "
    panes = iter(
        [
            prompt_pane,
            "5h limit: 84% left · resets in 2h\n\n› ",
        ]
    )
    sent: list[str] = []
    keys: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "capture_pane", lambda: next(panes))
    monkeypatch.setattr(module, "send_text", lambda value: sent.append(value))
    monkeypatch.setattr(module, "send_keys", lambda *value: keys.append(value))

    assert (
        module.maybe_schedule_codex_account_capacity_probe(
            pane=prompt_pane,
            auth_mode="chatgpt",
        )
        is True
    )
    worker = module.CODEX_ACCOUNT_CAPACITY_PROBE_THREAD
    assert worker is not None
    worker.join(timeout=1)

    persisted = module.codex_account_capacity_snapshot(auth_mode="chatgpt")
    history_text = module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH.read_text(
        encoding="utf-8"
    )
    assert sent == ["/usage"]
    assert keys == [("Escape",), ("C-u",), ("C-a", "C-k"), ("C-l",)]
    assert persisted["state"] == "available"
    assert persisted["minimum_window_percent_left"] == 84
    assert "OpenAI Codex" not in history_text
    assert "5h limit" not in history_text

    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: True)
    assert (
        module.maybe_schedule_codex_account_capacity_probe(
            pane=prompt_pane,
            auth_mode="chatgpt",
        )
        is False
    )

    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    assert (
        module.maybe_schedule_codex_account_capacity_probe(
            pane="OpenAI Codex (v0.118.0)\n\n› unfinished draft",
            auth_mode="chatgpt",
        )
        is False
    )


def test_codex_account_capacity_probe_uses_configured_fallback_without_pane_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_agent_console_web()
    module.CODEX_ACCOUNT_CAPACITY_PATH = tmp_path / "capacity.json"
    module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH = tmp_path / "capacity.jsonl"
    module.CODEX_ACCOUNT_CAPACITY_PROBE_TIMEOUT_SECONDS = 0.001
    module.CODEX_ACCOUNT_CAPACITY_PROBE_POLL_SECONDS = 0.01
    module.CODEX_ACCOUNT_CAPACITY_PROBE_THREAD = None
    module.CODEX_ACCOUNT_CAPACITY_COMMAND = "/usage"
    module.CODEX_ACCOUNT_CAPACITY_FALLBACK_COMMAND = "/plan-limits"
    monkeypatch.setattr(module, "stored_codex_auth_mode", lambda: "chatgpt")
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(module, "prompt_thread_alive", lambda: False)
    prompt_pane = "OpenAI Codex (v0.118.0)\n\n› "
    panes = iter(
        [
            prompt_pane,
            "Account token usage is available for this account.\n\n› ",
            "No aggregate capacity was returned.\n\n› ",
            "5h limit: 72% remaining · resets in 1h\n\n› ",
        ]
    )
    sent: list[str] = []
    keys: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "capture_pane", lambda: next(panes))
    monkeypatch.setattr(module, "send_text", lambda value: sent.append(value))
    monkeypatch.setattr(module, "send_keys", lambda *value: keys.append(value))

    assert (
        module.maybe_schedule_codex_account_capacity_probe(
            pane=prompt_pane,
            auth_mode="chatgpt",
        )
        is True
    )
    worker = module.CODEX_ACCOUNT_CAPACITY_PROBE_THREAD
    assert worker is not None
    worker.join(timeout=1)

    persisted = module.codex_account_capacity_snapshot(auth_mode="chatgpt")
    history_text = module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH.read_text(
        encoding="utf-8"
    )
    assert sent == ["/usage", "/plan-limits"]
    assert keys == [
        ("Escape",),
        ("C-u",),
        ("C-a", "C-k"),
        ("C-l",),
        ("Escape",),
        ("C-u",),
        ("C-a", "C-k"),
        ("C-l",),
    ]
    assert persisted["minimum_window_percent_left"] == 72
    assert "Account token usage" not in history_text
    assert "5h limit" not in history_text


def test_codex_account_capacity_unsupported_usage_command_is_sanitized_and_backed_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_agent_console_web()
    module.CODEX_ACCOUNT_CAPACITY_PATH = tmp_path / "capacity.json"
    module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH = tmp_path / "capacity.jsonl"
    module.CODEX_ACCOUNT_CAPACITY_PROBE_TIMEOUT_SECONDS = 0.001
    module.CODEX_ACCOUNT_CAPACITY_PROBE_POLL_SECONDS = 0.01
    module.CODEX_ACCOUNT_CAPACITY_PROBE_THREAD = None
    module.CODEX_ACCOUNT_CAPACITY_COMMAND = "/usage"
    module.CODEX_ACCOUNT_CAPACITY_FALLBACK_COMMAND = ""
    monkeypatch.setattr(module, "stored_codex_auth_mode", lambda: "chatgpt")
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: False)
    monkeypatch.setattr(module, "prompt_thread_alive", lambda: False)
    prompt_pane = "OpenAI Codex (v0.144.4)\n\n› "
    unsupported_pane = "Unrecognized command '/usage'. Type \"/\" for a list of supported commands.\n\n› "
    panes = iter([prompt_pane, unsupported_pane, unsupported_pane])
    sent: list[str] = []
    keys: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "capture_pane", lambda: next(panes))
    monkeypatch.setattr(module, "send_text", lambda value: sent.append(value))
    monkeypatch.setattr(module, "send_keys", lambda *value: keys.append(value))

    assert (
        module.maybe_schedule_codex_account_capacity_probe(
            pane=prompt_pane,
            auth_mode="chatgpt",
        )
        is True
    )
    worker = module.CODEX_ACCOUNT_CAPACITY_PROBE_THREAD
    assert worker is not None
    worker.join(timeout=1)

    persisted = module.codex_account_capacity_snapshot(auth_mode="chatgpt")
    history_text = module.CODEX_ACCOUNT_CAPACITY_HISTORY_PATH.read_text(
        encoding="utf-8"
    )
    assert sent == ["/usage"]
    assert keys == [("Escape",), ("C-u",), ("C-a", "C-k"), ("C-l",)]
    assert persisted["source"] == "unsupported_command"
    assert persisted["state"] == "unknown"
    assert persisted["eligible_for_subscription_route"] is False
    assert "Unrecognized command" not in history_text
    assert "/usage" not in history_text
    assert (
        module.maybe_schedule_codex_account_capacity_probe(
            pane=prompt_pane,
            auth_mode="chatgpt",
        )
        is False
    )
