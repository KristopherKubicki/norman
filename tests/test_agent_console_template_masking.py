from __future__ import annotations

import io
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


def _jsdom_module_path() -> Path:
    path = Path(__file__).resolve().parents[1] / "node_modules" / "jsdom"
    if not path.exists():
        pytest.skip("node_modules/jsdom is not installed in this handoff pack")
    return path


def _load_agent_console_web():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_template"
        / "agent_console_web.py"
    )
    tier_env_keys = (
        "NORMAN_CODEX_DIRECT_TIERS_ENABLED",
        "HOUSEBOT_CODEX_DIRECT_TIERS_ENABLED",
        "NORMAN_CODEX_SERVICE_TIER",
        "HOUSEBOT_CODEX_SERVICE_TIER",
        "OPENAI_SERVICE_TIER",
        "NORMAN_CODEX_STANDARD_PROFILE_V2",
        "HOUSEBOT_CODEX_STANDARD_PROFILE_V2",
        "NORMAN_CODEX_DEFAULT_PROFILE_V2",
        "HOUSEBOT_CODEX_DEFAULT_PROFILE_V2",
        "NORMAN_CODEX_BEDROCK_PROFILE_V2",
        "HOUSEBOT_CODEX_BEDROCK_PROFILE_V2",
        "NORMAN_CODEX_STANDARD_MODEL",
        "HOUSEBOT_CODEX_STANDARD_MODEL",
        "NORMAN_CODEX_BEDROCK_FAILOVER_PROFILE_V2",
        "HOUSEBOT_CODEX_BEDROCK_FAILOVER_PROFILE_V2",
        "NORMAN_CODEX_BEDROCK_FAILOVER_MODEL",
        "HOUSEBOT_CODEX_BEDROCK_FAILOVER_MODEL",
        "NORMAN_CODEX_BEDROCK_FAILOVER_PROVIDER_LABEL",
        "HOUSEBOT_CODEX_BEDROCK_FAILOVER_PROVIDER_LABEL",
        "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_PROFILE",
        "HOUSEBOT_CODEX_BEDROCK_FAILOVER_AWS_PROFILE",
        "NORMAN_CODEX_BEDROCK_FAILOVER_AWS_REGION",
        "HOUSEBOT_CODEX_BEDROCK_FAILOVER_AWS_REGION",
        "NORMAN_CODEX_DIRECT_MODEL",
        "HOUSEBOT_CODEX_DIRECT_MODEL",
        "NORMAN_CODEX_FLEX_MODEL",
        "HOUSEBOT_CODEX_FLEX_MODEL",
        "NORMAN_CODEX_PRIORITY_MODEL",
        "HOUSEBOT_CODEX_PRIORITY_MODEL",
        "NORMAN_CODEX_STANDARD_AWS_PROFILE",
        "HOUSEBOT_CODEX_STANDARD_AWS_PROFILE",
        "NORMAN_CODEX_STANDARD_AWS_REGION",
        "HOUSEBOT_CODEX_STANDARD_AWS_REGION",
    )
    tier_env = {key: os.environ.pop(key, None) for key in tier_env_keys}
    os.environ["NORMAN_CODEX_SERVICE_TIER"] = "auto"
    os.environ["HOUSEBOT_CODEX_SERVICE_TIER"] = "auto"
    os.environ["NORMAN_CODEX_DIRECT_TIERS_ENABLED"] = "1"
    os.environ["HOUSEBOT_CODEX_DIRECT_TIERS_ENABLED"] = "1"
    spec = importlib.util.spec_from_file_location("agent_console_web", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for key, value in tier_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
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


def _norman_codex_launch_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "scripts" / "norman_codex_launch.sh"
    ).read_text(encoding="utf-8")


def _norman_bot_prime_start_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "scripts" / "norman_bot_prime_start.sh"
    ).read_text(encoding="utf-8")


def _launch_policy_block(source: str) -> str:
    match = re.search(
        r"Fleet coordination policy:\n(?P<body>.*?)\nEOF",
        source,
        flags=re.DOTALL,
    )
    assert match
    return match.group("body")


def _bbs_doctor_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "scripts" / "bbs_doctor.py"
    ).read_text(encoding="utf-8")


def _load_bbs_doctor():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "bbs_doctor.py"
    spec = importlib.util.spec_from_file_location("bbs_doctor", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _texture_reference_cards() -> dict[str, dict]:
    reference_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "textures"
        / "tui_microtexture_reference.json"
    )
    return {
        card["slug"]: card
        for card in json.loads(reference_path.read_text(encoding="utf-8"))
    }


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
    assert "Interrupt Latest" in source
    assert "Interrupt tmux Session" in source
    assert '"/api/cancel-web"' in source
    assert '"/api/cancel-all"' in source
    assert '"/api/queue/clear"' in source
    assert '"/api/queue/delete"' in source
    assert '"/api/queue/promote-latest"' in source
    assert '"/api/queue/interrupt"' in source
    assert '"/api/queue/interrupt-latest"' in source
    assert "queue-interrupt-button" in source
    assert "upgradeQueuedPromptToInterrupt" in source
    assert "Working on:" in source
    assert "New messages will be queued" in source
    assert "Interrupt prompts wait for the next safe checkpoint" in source
    assert 'id="prompt-interlace-mode-input"' in source
    assert 'id="interlace-mode-range"' not in source
    assert 'id="interrupt-submit-button"' in source
    assert "Interrupt ack" in source
    assert "Queue mode waits for the active reply to finish" in source
    assert "BBS / passive" in source
    assert 'const queueStateLabel = queueSource === "recovered"' in source
    assert '? "Interrupt ack"' in source
    assert '].filter(Boolean).join(" · ");' in source
    assert "Remove this queued prompt" in source
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

    assert (
        "function extractPreviewableFileTargets(value, limit = INLINE_FILE_TARGET_LIMIT)"
        in source
    )
    assert "const INLINE_FILE_TARGET_LIMIT = 6;" in source
    assert "const INLINE_IMAGE_GALLERY_LIMIT = 6;" in source
    assert "const WORKDIR =" in source
    assert "function fullFileTarget(value)" in source
    assert "const FILE_ABSOLUTE_ROOTS = Object.freeze" in source
    assert "const WEB_ROUTE_TARGET_PREFIXES = Object.freeze" in source
    assert "function looksLikeWebRouteTarget(value)" in source
    assert "function looksLikeKnownAbsoluteFileRoot(value)" in source
    assert "looksLikeRelativeFileTarget(value)" in source
    assert 'if (clean.startsWith("/")) {{' in source
    assert "function collectAbsoluteFileHints(value)" in source
    assert "function resolveRelativeFileTargetFromHints(value, absoluteHints)" in source
    assert "const absoluteHints = collectAbsoluteFileHints(text);" in source
    assert "resolveRelativeFileTargetFromHints(clean, absoluteHints)" in source
    assert r"text.matchAll(/\[([^\]]+)\]\s*\(\s*(<[^>\\n]+>|[^\s)]+)\s*\)/g)" in source
    assert "fullFileTarget(clean) || clean" in source
    assert "function loadInlineFilePreview(entry)" in source
    assert (
        'const normalized = raw.replace(/\\\\r\\\\n/g, "\\\\n").replace(/\\\\r/g, "\\\\n");'
        in source
    )
    assert 'const lines = normalized.split("\\\\n");' in source
    assert "function renderInlineFilePreviews(container, targets)" in source
    assert ".message-file-previews {" in source
    assert ".inline-file-preview-body img {" in source
    assert '.inline-file-preview[data-preview-error="load_failed"]' in source
    assert "function markInlinePreviewLoadFailed(card, summary, body, entry" in source
    assert "Preview could not load from this TUI host." in source
    assert ".inline-image-preview-error {" in source
    assert "preview unavailable" in source
    assert 'class="route-link"' in source
    assert "Route-relative URL. Not embedded as a local file preview" in source
    assert ".inline-file-preview-actions {" in source
    assert 'pre.className = "inline-file-preview-text";' in source
    assert 'previews.className = "message-file-previews";' in source
    assert "renderInlineFilePreviews(previews, previewTargets);" in source


def test_chat_file_links_embed_inline_media_players() -> None:
    source = _agent_console_web_source()

    assert "function mediaKindForFilePath(value) {{" in source
    assert "function mediaMimeTypeForPath(value) {{" in source
    assert 'return "video";' in source
    assert 'return "audio";' in source
    assert "const mediaKind = mediaKindForFilePath(clean);" in source
    assert 'if (kind === "video" || kind === "audio") {{' in source
    assert "mediaType: mediaMimeTypeForPath(cacheKey)," in source
    assert (
        'const isInlineMedia = entry.kind === "video" || entry.kind === "audio";'
        in source
    )
    assert 'video: "VID"' in source
    assert 'audio: "AUD"' in source
    assert (
        "shell.className = `inline-media-player inline-media-player-${{payload.kind}}`;"
        in source
    )
    assert (
        'const player = document.createElement(payload.kind === "video" ? "video" : "audio");'
        in source
    )
    assert "player.controls = true;" in source
    assert 'player.preload = "metadata";' in source
    assert "player.playsInline = true;" in source
    assert "void setExpanded(true);" in source
    assert ".inline-media-player video {{" in source
    assert ".inline-media-player audio {{" in source


def test_chat_file_links_embed_document_and_review_frame_previews() -> None:
    source = _agent_console_web_source()

    assert "function documentMimeTypeForPath(value) {{" in source
    assert 'return "application/pdf";' in source
    assert "function shouldAutoExpandInlinePreview(entry) {{" in source
    assert "contact[-_ ]?sheet" in source
    assert (
        "screenshot|screen[-_ ]?shot|capture|clipboard|upload|image|chart|graph|plot"
        in source
    )
    assert "if (/\\.pdf$/i.test(clean)) {{" in source
    assert 'return "pdf";' in source
    assert 'if (kind === "pdf") {{' in source
    assert "mediaType: documentMimeTypeForPath(cacheKey)," in source
    assert 'pdf: "PDF"' in source
    assert 'pdf: "PDF preview"' in source
    assert (
        'shell.className = "inline-document-viewer inline-document-viewer-pdf";'
        in source
    )
    assert 'const object = document.createElement("object");' in source
    assert 'object.type = payload.mediaType || "application/pdf";' in source
    assert 'fallback.textContent = "Open PDF preview";' in source
    assert "const autoExpandPreview = shouldAutoExpandInlinePreview(entry);" in source
    assert 'card.classList.add("inline-auto-preview");' in source
    assert ".inline-document-viewer object {{" in source
    assert ".inline-document-fallback {{" in source


def test_chat_messages_surface_compact_cost_and_low_value_error_controls() -> None:
    source = _agent_console_web_source()

    assert "function usageCostDescriptor(usage, snapshot = state.snapshot) {{" in source
    assert "function formatCompactUsd(value) {{" in source
    assert (
        "function publicUsageCostRatesForModel("
        "model, serviceTier = DEFAULT_SERVICE_TIER"
        ") {{" in source
    )
    assert 'modelLabel = "GPT-5.4"' in source
    assert "OpenAI Codex GPT-5.4 credit rate card" in source
    assert (
        'OpenAI ${{modelLabel}} ${{tierLabels[tier] || "Standard"}} public rate card'
        in source
    )
    assert "long-context uplift may apply above 272K input tokens" in source
    assert "costChipLabel" in source
    assert "function usageRateCardKey(model, serviceTier) {{" in source
    assert "const effectiveTier = normalizeServiceTier(" in source
    assert "Tier resolution:" in source
    assert "long-window" in source
    assert "This turn:" in source
    assert "Biller:" in source
    assert (
        "function estimateTurnUsd(inputTokens, cachedTokens, outputTokens, rates) {{"
        in source
    )
    assert "number >= 1000000000" in source
    assert '? "Baseline"' in source
    assert '? "provider baseline"' in source
    assert ".message-cost-chip," in source
    assert ".message-estimate-chip {{" in source
    assert "function turnEffortLedgerDescriptor(item, usage) {{" in source
    assert "function estimateToolCallBudgetForTurn(item, usage) {{" in source
    assert "Estimate versus actual for this turn." in source
    assert "Calls R${{expectedReasoningCalls}}/${{actualReasoningCalls}}" in source
    assert "Local usage estimate, not an invoice or credit-card charge" in source
    assert "Charge basis: personal Codex credit estimate" in source
    assert "F GPT-5.5/frontier calls:" in source
    assert 'costNode.className = "message-cost-chip";' in source
    assert 'effortNode.className = "message-estimate-chip";' in source
    assert "usage: item.usage || null" in source
    assert "function looksLikeLowValueRawError(value) {{" in source
    assert 'article.classList.add("low-value-error");' in source
    assert "Raw runtime fragment captured" in source


def test_service_tier_preferences_reset_stale_default_after_bedrock_migration() -> None:
    source = _agent_console_web_source()

    assert "const savedDefaultServiceTier = normalizeServiceTier(" in source
    assert "directTierExplicit: false" in source
    assert 'const savedDefaultChanged = DEFAULT_SERVICE_TIER !== "auto"' in source
    assert "const serviceTierCameFromSavedDefault =" in source
    assert "const staleDirectTierWithoutExplicitChoice =" in source
    assert 'savedDefaultServiceTier === "auto" && serviceTier === "flex"' in source
    assert "savedDefaultChanged && serviceTierCameFromSavedDefault" in source
    assert "staleDirectTierWithoutExplicitChoice" in source


def test_chat_surface_explains_rate_limit_backoff_and_usage_context() -> None:
    source = _agent_console_web_source()

    assert "function containsRateLimitError(value) {{" in source
    assert "function rateLimitBackoffRemaining(snapshot = state.snapshot) {{" in source
    assert "function usageSummaryForActiveWork(snapshot = state.snapshot) {{" in source
    assert "function rateLimitStatusCopy(snapshot = state.snapshot) {{" in source
    assert "Provider rate limit hit; backing off automatically" in source
    assert "current turn usage pending" in source
    assert "current turn waiting; no accepted model call yet" in source
    assert (
        "Provider rate limit hit. The TUI backs off and retries automatically" in source
    )


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


def test_sync_template_trusts_operator_devices_for_tokenless_console_only() -> None:
    source = _sync_agent_console_template_source()

    trusted_match = re.search(
        r"TRUSTED_CONSOLE_CLIENTS = \(\n(?P<body>.*?)\n\)",
        source,
        flags=re.DOTALL,
    )
    auth_bridge_match = re.search(
        r"AUTH_BRIDGE_CLIENTS = \(\n(?P<body>.*?)\n\)",
        source,
        flags=re.DOTALL,
    )
    assert trusted_match
    assert auth_bridge_match

    trusted_body = trusted_match.group("body")
    auth_bridge_body = auth_bridge_match.group("body")

    for expected in (
        '"192.168.2.241",  # norman LAN/front door',
        '"100.103.34.17",  # norman tailnet/front door',
        '"fd7a:115c:a1e0::3438:2211",  # norman tailnet/front door ipv6',
        '"192.168.2.136",  # pixel10',
        '"100.78.41.73",  # pixel10 tailnet',
        '"fd7a:115c:a1e0::4d33:2949",  # pixel10 tailnet ipv6',
        '"192.168.2.137",  # hal desktop',
        '"100.112.62.71",  # hal tailnet',
        '"192.168.2.140",  # plasma-mobile',
        '"100.109.202.7",  # plasma-mobile tailnet',
    ):
        assert expected in trusted_body
        assert expected not in auth_bridge_body

    assert '"127.0.0.1"' in auth_bridge_match.group("body")
    assert '"::1"' in auth_bridge_match.group("body")


def test_sync_template_trusts_sal_for_requested_work_consoles_only() -> None:
    module = _load_sync_agent_console_template()

    for name in module.WORK_SPECIAL_SAL_CONSOLE_INSTANCES:
        trusted = module.trusted_console_clients_for_instance(name)
        assert "192.168.2.141" in trusted
        assert "100.77.147.57" in trusted

    assert "leadership-kpis" in module.WORK_SPECIAL_SAL_CONSOLE_INSTANCES
    housebot_trusted = module.trusted_console_clients_for_instance("housebot")
    assert "192.168.2.141" not in housebot_trusted
    assert "100.77.147.57" not in housebot_trusted


def test_sync_template_keeps_netops_direct_without_work_sal_trust() -> None:
    module = _load_sync_agent_console_template()

    assert "networking" not in module.WORK_BEDROCK_DEFAULT_INSTANCES
    assert "networking" not in module.WORK_SPECIAL_SAL_CONSOLE_INSTANCES
    networking_trusted = module.trusted_console_clients_for_instance("networking")
    assert "192.168.2.141" not in networking_trusted
    assert "100.77.147.57" not in networking_trusted


def test_sync_template_seeds_bbs_summary_configuration() -> None:
    source = _sync_agent_console_template_source()

    assert "DEFAULT_BBS_SUMMARY_URL = os.environ.get(" in source
    assert '"NORMAN_SYNC_BBS_URL", "http://192.168.2.241:8765"' in source
    assert '"NORMAN_CODEX_BBS_URL": DEFAULT_BBS_SUMMARY_URL' in source
    assert "bbs_actor = BBS_ACTOR_OVERRIDES.get(instance.name, instance.name)" in source
    assert 'bbs_env_file = f"/etc/{instance.name}/switchboard-bbs.env"' in source
    assert '"NORMAN_CODEX_BBS_ACTOR": bbs_actor' in source
    assert '"NORMAN_CODEX_BBS_ENV_FILE": bbs_env_file' in source
    assert '"SWITCHBOARD_URL": DEFAULT_BBS_SUMMARY_URL' in source
    assert '"SWITCHBOARD_ACTOR": bbs_actor' in source
    assert '"SWITCHBOARD_ENV_FILE": bbs_env_file' in source
    assert '"networking": "netops"' in source
    assert '"phone-ops": "phoneops"' in source
    assert '"studio": "camera-studio"' in source


def test_sync_template_installs_bbs_helpers_next_to_launchers() -> None:
    module = _load_sync_agent_console_template()
    instance = module.ConsoleInstance(
        name="panelbot",
        host_name="work-special",
        ssh_target="root@192.168.2.147",
        use_sudo=False,
        env_file="/etc/panelbot/codex-web.env",
        web_path="/home/kristopher/code/d.ace/scripts/panelbot_codex_web.py",
        launch_path="/home/kristopher/code/d.ace/scripts/panelbot_codex_launch.sh",
        supervisor_path="/home/kristopher/code/d.ace/scripts/panelbot_codex_supervisor.sh",
        restart_units=("panelbot-codex-web.service",),
        agent_label="Panelbot",
        web_port="8788",
        web_token="",
        prompt_file="/etc/panelbot/codex-system-prompt.txt",
        codex_home="/home/kristopher/.codex-panelbot",
    )

    assert module.SOURCE_FILES["bbs-lifecycle"].name == "bbs_task_lifecycle.py"
    assert module.SOURCE_FILES["bbs-janitor"].name == "bbs_janitor.py"
    assert module.SOURCE_FILES["memory-tool"].name == "tui_memory_tool.py"
    assert (
        "bbs-lifecycle",
        "/home/kristopher/code/d.ace/scripts/bbs_task_lifecycle.py",
    ) in instance.files
    assert (
        "bbs-janitor",
        "/home/kristopher/code/d.ace/scripts/bbs_janitor.py",
    ) in instance.files
    assert (
        "memory-tool",
        "/home/kristopher/code/d.ace/scripts/tui_memory_tool.py",
    ) in instance.files


def test_sync_template_remote_state_tolerates_numeric_owner_ids() -> None:
    source = _sync_agent_console_template_source()

    assert "def owner_name(uid):" in source
    assert "except KeyError:" in source
    assert "return str(uid)" in source
    assert "return str(gid)" in source


def test_sync_template_seeds_long_job_notification_defaults() -> None:
    source = _sync_agent_console_template_source()
    web_source = _agent_console_web_source()

    assert "NORMAN_SYNC_LONG_JOB_NOTIFY_THRESHOLD_SECONDS" in source
    assert "NORMAN_SYNC_LONG_JOB_NOTIFY_URL" in source
    assert "NORMAN_SYNC_LONG_JOB_NOTIFY_TOKEN" in source
    assert '"NORMAN_CODEX_LONG_JOB_NOTIFY_THRESHOLD_SECONDS"' in source
    assert "NORMAN_CODEX_LONG_JOB_NOTIFY_URL" in web_source
    assert "NORMAN_CODEX_LONG_JOB_NOTIFY_COMMAND" in web_source
    assert "/api/long-job-notify" in web_source
    assert "notification.long-job.sent" in web_source


def test_switchboard_start_uses_localhost_only_auth_bridge() -> None:
    source = _norman_bot_prime_start_source()

    assert "NORMAN_CODEX_BROWSER_AUTH_CLIENTS:-127.0.0.1,::1" in source
    assert "NORMAN_CODEX_BROWSER_AUTH_CLIENTS:-127.0.0.1,::1,192." not in source
    assert (
        "NORMAN_CODEX_TRUSTED_CLIENTS:-127.0.0.1,::1,192.168.2.241,"
        "100.103.34.17,fd7a:115c:a1e0::3438:2211,192.168.2.136,"
        "100.78.41.73,fd7a:115c:a1e0::4d33:2949" in source
    )
    assert (
        "NORMAN_CODEX_TRUSTED_PROXIES:-127.0.0.1,::1,192.168.2.241,"
        "100.103.34.17,fd7a:115c:a1e0::3438:2211" in source
    )


def test_switchboard_start_discovers_newest_node_runtime() -> None:
    source = _norman_bot_prime_start_source()

    assert "NORMAN_CODEX_NODE_PATHS" in source
    assert "NORMAN_CODEX_NODE_DIR" in source
    assert "NORMAN_CODEX_NODE_BIN" in source
    assert 'collect_node_bin_dirs "/opt/node-v*/bin"' in source
    assert 'collect_node_bin_dirs "/home/operator/.nvm/versions/node/v*/bin"' in source
    assert (
        'collect_node_bin_dirs "/home/kristopher/.nvm/versions/node/v*/bin"' in source
    )
    assert 'PATH="/opt/node-v20.19.6/bin:' not in source


def test_prompt_input_rerouted_plain_text_paste_inserts_into_composer() -> None:
    source = _agent_console_web_source()

    assert "function insertTextIntoPrompt(text, options = {{}})" in source
    assert (
        "const reroutedPaste = Boolean(event && event.target && event.target !== el.promptInput);"
        in source
    )
    assert "insertTextIntoPrompt(pastedText, {{ placeAtEnd: true }});" in source


def test_prompt_input_condenses_multiline_clipboard_text_into_block_chip() -> None:
    source = _agent_console_web_source()

    assert "const PASTE_BLOCK_MIN_CHARS = 280;" in source
    assert "const PASTE_BLOCK_MIN_LINES = 2;" in source
    assert "const PASTE_BLOCK_ALWAYS_LINES = 4;" in source
    assert "function looksLikePasteBlock(value) {{" in source
    assert "lineCount >= PASTE_BLOCK_ALWAYS_LINES" in source
    assert (
        "lineCount >= PASTE_BLOCK_MIN_LINES && text.length >= PASTE_BLOCK_MIN_CHARS"
        in source
    )
    assert "if (!looksLikePasteBlock(pastedText)) {{" in source
    assert "return `[${{attachmentTokenLabel(entry)}}]`;" in source
    assert 'source: options.source || "paste-block"' in source


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


def test_template_exposes_human_intervention_loop() -> None:
    source = _agent_console_web_source()

    assert "CREATE TABLE IF NOT EXISTS human_interventions" in source
    assert "HUMAN_INTERVENTION_SUPPRESS_SECONDS" in source
    assert "def upsert_human_intervention(value: dict[str, Any])" in source
    assert "def update_human_intervention_status(" in source
    assert "def detect_human_interventions(snapshot: dict[str, Any])" in source
    assert "actor_not_allowed_for_target" in source
    assert "stale_web_prompt_after_restart" in source
    assert "human_intervention.raised" in source
    assert "human_intervention.actioned" in source
    assert '"/api/human-intervention/action"' in source
    assert "function humanInterventionFocus(snapshot)" in source
    assert "function humanInterventionCapsuleState(snapshot)" in source
    assert "function humanInterventionActionButtons(item)" in source
    assert "function humanInterventionEvidenceLine(item)" in source
    assert "function humanInterventionWhyLine(item)" in source
    assert "function humanInterventionNeedLine(item)" in source
    assert "function humanInterventionApprovalAsk(item)" in source
    assert "function humanInterventionFinePrint(item)" in source
    assert "Prompt parked after restart" in source
    assert "Review the parked prompt first." in source
    assert "Review, Draft note, and Close alert are local." in source
    assert '"stale_web_prompt_after_restart",' in source
    assert "not automatically a provider, sign-in, or captcha failure" in source
    assert 'label: "Review"' in source
    assert "Use only when you want a fresh model turn" in source
    assert "Review the abandoned web prompt after restart for this TUI." in source
    assert "toast-source" in source
    assert "toast-alert-brief" in source
    assert "Operator alert summary" in source
    assert "toast-alert-label" in source
    assert "toast-fineprint" in source
    assert "<summary>Fine print</summary>" in source
    assert "Fine print: Approve queues a model prompt and may spend tokens." in source
    assert "function detectReadingScale()" in source
    assert "function normalizeTextZoom(value)" in source
    assert 'data-setting="textZoom" data-value="auto"' in source
    assert 'data-setting="textZoom" data-value="large"' in source
    assert 'textZoom: "auto"' in source
    assert 'body[data-reading-scale="wide"]' in source
    assert 'body[data-reading-scale="large"]' in source
    assert 'body[data-layout-mode="full"][data-reading-scale="large"] .topbar' in source
    assert "flex: 1 1 32rem;" in source
    assert "max-width: min(100%, 78rem);" in source
    assert "--composer-input-size" in source
    assert "shellWidth >= 2300 && shellHeight >= 980" in source
    assert "actionable_high" in source
    assert "def _sentinel_visible_bbs_priority_count(" in source
    assert "function handleHumanInterventionAction(item, action)" in source
    assert "function appendHumanInterventionActions(container, item)" in source
    assert "function humanInterventionNextStep(item)" in source
    assert 'label: "Needs You"' in source
    assert 'label: "Access done"' in source
    assert 'label: "Approve"' in source
    assert 'label: "Resolve"' in source
    assert 'label: "Details"' in source
    assert 'label: "Close alert"' in source
    assert 'className = "toast-actions"' in source
    assert "].slice(0, 4);" in source
    assert 'className = "toast-action-key"' in source
    assert 'className = "toast-action-impact"' in source
    assert 'data-slot="human-intervention-actions"' in source
    assert "Opened intervention details. No model call was made." in source
    assert 'value: askNow > 1 ? `${{askNow}} asks` : "1 ask"' in source
    assert "Needs you:" in source


def test_human_intervention_action_closes_and_suppresses_recent_reopen(
    tmp_path: Path,
) -> None:
    module = _load_agent_console_web()
    module.STATE_DIR = tmp_path
    module.STATE_DB_PATH = tmp_path / "tui_state.sqlite3"
    module.AUDIT_PATH = tmp_path / "audit.jsonl"
    module.THREAD_ID_PATH = tmp_path / "thread_id.txt"

    payload = {
        "kind": "auth_or_human_gate",
        "severity": "ask_now",
        "fingerprint": "auth_or_human_gate:test-thread",
        "question": "Can you complete the sign-in?",
        "detail": "Detected a browser sign-in gate.",
        "options": ["Complete the human gate now", "Defer"],
        "thread_id": "thread-123",
    }

    created = module.upsert_human_intervention(payload)
    assert created["status"] == "open"

    updated = module.update_human_intervention_status(
        created["id"],
        "not_actionable",
        note="not relevant anymore",
        actor_ip="127.0.0.1",
    )
    assert updated["status"] == "canceled"
    assert updated["closed_at"] > 0
    assert updated["evidence"]["operator_action"] == "not_actionable"

    reopened = module.upsert_human_intervention(payload)
    assert reopened["status"] == "canceled"
    assert module.load_human_interventions() == []


def test_template_exposes_observe_only_sentinel_loop() -> None:
    source = _agent_console_web_source()

    assert 'NORMAN_CODEX_SENTINEL_MODE", "observe_only"' in source
    assert 'NORMAN_CODEX_SENTINEL_LLM_ENABLED", "0"' in source
    assert "NORMAN_CODEX_SENTINEL_MAX_LLM_TOKENS_PER_DAY" in source
    assert "def build_sentinel_state(" in source
    assert "def maybe_raise_sentinel_intervention(" in source
    assert "norman.tui.sentinel.v1" in source
    assert "function sentinelCapsuleState(snapshot)" in source
    assert 'label: "Sentinel"' in source
    assert "Sentinel LLM budget: 0 tokens/day" in source


def test_activity_strip_copy_and_canvas_focus_hooks_are_present() -> None:
    source = _agent_console_web_source()

    assert 'line: "Sending to worker"' in source
    assert 'label: "Accepted"' in source
    assert 'label: "Return reply"' in source
    assert "function activityStepProgress(steps)" in source
    assert "function activityTrackSummary(steps)" in source
    assert "function workLedgerState(snapshot, insight = null)" in source
    assert "function conciseBbsLedger(snapshot)" in source
    assert (
        "grid-template-columns: auto minmax(0, 1fr) minmax(124px, 22vw) auto;" in source
    )
    assert 'id="work-ledger"' in source
    assert ".activity-strip.bbs" in source
    assert "BBS watcher active" in source
    assert "restart staged" in source
    assert 'startedParts.find((item) => item.includes("in flight")) || ""' in source
    assert 'queueDepth > 0 ? `+${{queueDepth}} queued` : ""' in source
    assert 'class="activity-track-bar"' in source
    assert 'class="activity-track-summary"' in source
    assert "scheduleComposerReserve({{ preserveLiveEdge: true }});" in source
    assert "function shouldFocusPromptFromCanvasClick(event)" in source
    assert 'el.workspace.addEventListener("click", (event) => {' in source


def test_activity_strip_promotes_bbs_background_state() -> None:
    source = _agent_console_web_source()

    assert "key: `bbs:${{bbsSignal.key}}`" in source
    assert 'label: bbsSignal.label || "BBS active"' in source
    assert "BBS inbound/outbound active" in source
    assert "BBS inbound active" in source
    assert "BBS outbound active" in source
    assert "const issueInsight = runtimeIssue(snapshot);" in source
    assert "if (issueInsight?.mode) {{" in source
    assert "statusText = `Ready. ${{bbsSignal.label}}: ${{bbsSignal.copy}}`" in source


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


def test_initial_conversation_does_not_duplicate_pending_prompt_already_in_history() -> (
    None
):
    module = _load_agent_console_web()

    snapshot = {
        "history": [
            {
                "prompt": "same prompt",
                "response": "[waiting for reply]",
                "error": "",
                "started_at": 100,
                "finished_at": 0,
                "speed": "balanced",
                "detail": 3,
            }
        ],
        "pending": True,
        "running_prompt": "same prompt",
        "last_started_at": 100,
        "running_speed": "balanced",
        "running_detail": 3,
        "status_message": "Working...",
    }

    rendered = module._initial_conversation_html(snapshot)

    assert rendered.count('class="message user"') == 1
    assert rendered.count("same prompt") == 1
    assert 'class="message assistant pending"' in rendered


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
    assert '.message.pending.live-status[data-live-status-stage="expanded"] {' in source
    assert ".message.pending.live-status .message-head {" in source
    assert "display: none;" in source
    assert ".message.pending.live-status .message-body::before {" in source
    assert ".message.pending.live-status .message-body::after {" in source
    assert "article.dataset.liveStatusStage" in source
    assert "const liveExpanded = liveStatusExpanded(snapshot, elapsed);" in source
    assert "const liveStatusBody = liveStatusBodyForSnapshot(" in source
    assert "Provider rate limit hit; backing off automatically" in source
    assert "function activeTurnPlan(snapshot = state.snapshot) {{" in source
    assert "function turnPlanEstimateCopy(plan) {{" in source
    assert "function liveStatusExpanded(snapshot, elapsed) {{" in source
    assert "function liveTurnProgressCopy(snapshot = state.snapshot) {{" in source
    assert (
        "function liveStatusBodyForSnapshot(snapshot, elapsed, usageCopy, modelState, expanded = false) {{"
        in source
    )
    assert "Plan:" in source
    assert "Next:" in source
    assert "Progress:" in source
    assert "Estimate:" in source
    assert "`Working on: ${{understood}}.`" in source
    assert "followupFlowCopy(snapshot)" in source
    assert "New messages will be queued" in source
    assert "use Interrupt for a safe-checkpoint handoff" in source
    assert 'snapshot.model_process_alive ? "model process alive"' in source


def test_live_turn_tracks_tools_files_decisions_and_tokens() -> None:
    module = _load_agent_console_web()

    live = module.initial_live_turn(
        prompt="Please inspect scripts/foo.py and decide what changed.",
        attachments=[],
        started_at=100,
        runtime="codex",
        model="gpt-5",
        service_tier="auto",
        job_budget="normal",
    )
    tool_event = {
        "type": "tool.started",
        "tool": "exec_command",
        "command": "sed -n '1,5p' scripts/foo.py",
    }
    live = module.live_turn_with_event(
        live,
        tool_event,
        kind=module.codex_event_checkpoint_kind(tool_event),
        observed_at=112,
    )
    decision_event = {"type": "agent_reasoning.done", "item": {"type": "reasoning"}}
    live = module.live_turn_with_event(
        live,
        decision_event,
        kind=module.codex_event_checkpoint_kind(decision_event),
        observed_at=118,
    )
    usage_event = {
        "type": "turn.completed",
        "usage": {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200},
    }
    live = module.live_turn_with_event(
        live,
        usage_event,
        kind=module.codex_event_checkpoint_kind(usage_event),
        observed_at=130,
    )
    snapshot = module.live_turn_snapshot(live, pending=True, observed_at=132)

    assert snapshot["state"] == "running"
    assert snapshot["elapsed_seconds"] == 32
    assert snapshot["event_count"] == 3
    assert snapshot["tool_event_count"] == 1
    assert snapshot["tool_started_count"] == 1
    assert snapshot["last_tool"] == "exec_command"
    assert "scripts/foo.py" in snapshot["files"]
    assert snapshot["file_interaction_count"] == 1
    assert snapshot["decision_count"] == 1
    assert snapshot["last_decision"] == "reasoning"
    assert snapshot["observed_total_tokens"] == 1200
    assert snapshot["token_source"] == "observed"


def test_agent_console_template_exposes_live_turn_runtime_metrics() -> None:
    source = _agent_console_web_source()

    assert '"live_turn": default_live_turn()' in source
    assert '"turn_plan": default_turn_plan_estimate()' in source
    assert "def record_live_turn_event" in source
    assert "record_live_turn_event(event, kind=kind)" in source
    assert '"live_turn": live_turn_snapshot(' in source
    assert '"turn_plan": normalize_turn_plan_estimate(meta.get("turn_plan"))' in source
    assert 'event_type="chat.plan-estimate"' in source
    assert "finalize_turn_plan_estimate(" in source
    assert '"turn_plan": final_turn_plan' in source
    assert 'json.dumps(snapshot.get("live_turn") or {}, sort_keys=True)' in source
    assert "function liveTurnCapsuleState(snapshot) {{" in source
    assert 'id="response-live-frame"' in source
    assert 'responseLiveFrame: document.getElementById("response-live-frame")' in source
    assert "function liveTurnRenderSignature(live) {{" in source
    assert "live_turn: liveTurnRenderSignature(snapshot?.live_turn)" in source
    assert "function responseLiveFrameState(snapshot = state.snapshot) {{" in source
    assert "function renderResponseLiveFrame(snapshot = state.snapshot) {{" in source
    assert "renderResponseLiveFrame(snapshot);" in source
    assert "Provider response streaming" in source
    assert "response-live-step" in source
    assert "const liveMetricRows = live.hidden ? [] : [" in source
    assert 'label: "Live tools"' in source
    assert 'label: "Decisions"' in source
    assert 'label: "Files touched"' in source


def test_agent_console_template_surfaces_auto_turn_control_chips() -> None:
    source = _agent_console_web_source()

    assert '"running_turn_control": {}' in source
    assert '"running_turn_control": (' in source
    assert "function runningTurnControl(snapshot = state.snapshot) {{" in source
    assert "function turnControlChips(snapshot = state.snapshot) {{" in source
    assert "function turnControlDetailCopy(snapshot = state.snapshot) {{" in source
    assert "approval first" in source
    assert (
        "preparing an estimate and approval checkpoint before spending hours" in source
    )
    assert "...turnControlChips(snapshot)" in source
    assert "liveTurnTokenLabel(live)" in source


def test_turn_plan_estimate_tracks_planned_and_final_usage() -> None:
    module = _load_agent_console_web()

    plan = module.build_turn_plan_estimate(
        prompt="can you add the working screen plan estimate and run tests",
        attachments=[],
        runtime="codex",
        model="gpt-5.5",
        service_tier="auto",
        job_budget="normal",
        optimization_mode="auto",
        speed="careful",
        detail=4,
        timeout_seconds=3600,
        drift_assessment={"tone": "ok"},
        created_at=123,
    )
    final = module.finalize_turn_plan_estimate(
        plan,
        usage={"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
        finished_at=456,
        success=True,
    )

    assert plan["schema"] == "norman.tui.turn-plan-estimate.v1"
    assert plan["stage"] == "planned"
    assert plan["created_at"] == 123
    assert plan["understood_task"].startswith("Implement:")
    assert "code edit" in plan["skill_labels"]
    assert "verification" in plan["skill_labels"]
    assert plan["estimated_skill_count"] >= 3
    assert plan["estimated_tool_calls_max"] >= plan["estimated_tool_calls_min"] >= 1
    assert plan["estimated_total_tokens"] > plan["estimated_input_tokens"]
    assert plan["cost_rate_source"]
    assert final["stage"] == "final"
    assert final["finished_at"] == 456
    assert final["observed_total_tokens"] == 1500
    assert final["estimate_delta_tokens"] == 1500 - plan["estimated_total_tokens"]
    assert final["success"] is True


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
    assert ".composer-input-shell.tactile-pulse {" in source
    assert ".composer-send.is-pressed {" in source
    assert "const INTERACTION_TONES = {" in source
    assert 'function playInteractionTone(kind = "click"' in source
    assert 'function pulseComposerShell(kind = "click"' in source
    assert "bindTactileControls();" in source
    assert 'playInteractionTone("type");' in source
    assert "0 18px 42px rgba(8, 12, 18, 0.16)," in source
    assert "backdrop-filter: blur(14px) saturate(118%);" in source
    assert ".rich-table th + th," in source
    assert ".context-save-button {" in source
    assert '.context-save-button[data-save-tone="danger"] {' in source
    assert ".kpi-strip {" in source
    assert ".kpi-capsule {" in source
    assert "font-variant-numeric: tabular-nums;" in source
    assert "transform: translateY(-0.5px);" in source
    assert ".system-runtime-metrics {" in source
    assert "body.mobile-compose-mode .message-tools," in source
    assert "body.mobile-compose-mode #switcher-toggle-button {" in source


def test_template_exposes_norman_command_rail() -> None:
    source = _agent_console_web_source()

    assert 'data-agent-slug="{html.escape(AGENT_SLUG)}"' in source
    assert 'id="norman-command-rail"' in source
    assert 'id="norman-rail-estate"' in source
    assert 'id="norman-rail-bbs"' in source
    assert 'id="norman-rail-sentinel"' in source
    assert 'id="norman-rail-live"' in source
    assert 'id="norman-rail-cost"' in source
    assert 'body[data-agent-slug="norman"] .norman-command-rail {' in source
    assert "function renderNormanCommandRail(snapshot) {{" in source
    assert "setNormanCommandCell(el.normanRailEstate, items.estate);" in source
    assert "renderNormanCommandRail(snapshot);" in source


def test_template_compacts_norman_mobile_chrome() -> None:
    source = _agent_console_web_source()

    assert (
        'body[data-agent-slug="norman"] .norman-command-rail::-webkit-scrollbar {{'
        in source
    )
    assert ".norman-command-title {{\n        display: none;" in source
    assert "min-width: max(5.7rem, 28vw);" in source
    assert "padding: 3px 5px;" in source
    assert "scroll-snap-type: x proximity;" in source
    assert "max(3px, env(safe-area-inset-top))" in source
    assert "#run-state,\n      .topbar-version {{\n        display: none;" in source
    assert ".status-action-button::before {{" in source
    assert "bottom: calc(8px + env(safe-area-inset-bottom));" in source
    assert "max-height: min(58dvh, 360px);" in source
    assert "max-width: min(58vw, 15rem);" in source
    assert "min-height: 34px;" in source
    assert (
        "bottom: calc(var(--composer-reserve) + 78px + env(safe-area-inset-bottom));"
        in source
    )
    assert ".toast.monitor .toast-fineprint {{" in source
    assert ".toast.monitor .toast-fineprint-body {{" in source
    assert "max-height: min(18dvh, 112px);" in source
    assert "-webkit-line-clamp: 2;" in source
    assert (
        ".toast:not(.alert):not(.offline):not(.ack):not(.stale):not(.review):not(.queue):not(.warn) {{"
        in source
    )
    assert "max-height: 72px;" in source
    assert (
        ".toast:not(.alert):not(.offline):not(.ack):not(.stale):not(.review):not(.queue):not(.warn) .toast-action-slot,"
        in source
    )
    assert (
        "const isHandoffAttention = needsAck > 0 || waiting > 0 || missingContext > 0"
        in source
    )


def test_template_marks_status_actions_with_governance_consequences() -> None:
    source = _agent_console_web_source()

    assert "const GOVERNANCE_POWER_DETAILS = {{" in source
    assert "const GOVERNANCE_POWER_KEYWORDS = {{" in source
    assert (
        "function governancePowersForSnapshot(snapshot, descriptor = {{}}) {{" in source
    )
    assert "function setGovernanceButton(button, powers, options = {{}}) {{" in source
    assert 'data-governance-action="approval"' in source
    assert 'data-governance-action="mouth"' in source
    assert 'data-governance-power="none"' in source
    assert "governance: ${{consequence.meta}}" in source
    assert "el.statusActionButton.dataset.governanceTone" in source
    assert (
        "setGovernanceButton(el.statusHandleButton, descriptor.powers || []," in source
    )
    assert (
        ".status-action-controls .utility-button[data-governance-action]::after"
        in source
    )
    assert '.status-action-button[data-governance-tone="alert"]' in source


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
    assert "Filesystem path/link policy:" in source
    assert "include the full absolute path from this TUI's filesystem" in source
    assert "resolve it against the current TUI working directory" in source
    assert "Treat most TUI/web bot surfaces as the slow/default-cost path" in source
    assert "Norman Prime on norman.home.arpa is allowed to use the fast path" in source
    assert "Norman Switchboard party-line broadcast" in source
    assert "Absorb it quietly unless you are directly addressed" in source
    assert "STANDARD_PROFILE_V2=" in source
    assert 'CODEX_PROFILE_ARGS=(--profile-v2 "$STANDARD_PROFILE_V2")' in source
    assert 'export AWS_PROFILE="$STANDARD_AWS_PROFILE"' in source
    assert 'export AWS_REGION="$STANDARD_AWS_REGION"' in source
    assert '"${CODEX_PROFILE_ARGS[@]}"' in source
    assert '"${CODEX_SERVICE_TIER_ARGS[@]}"' in source
    assert "Scout/Ranger is the work research collection lane only." in source
    assert "Use Scout for external research, Perplexity/watchlists" in source
    assert "Do not send Scout implementation, deploys, credentials" in source
    assert "Switchboard BBS operating rules:" in source
    assert "never print or copy BBS tokens" in source
    assert (
        "A 403 when reading another actor's inbox, including Norman's, is expected"
        in source
    )
    assert "create or update a properly scoped handoff thread" in source
    assert "Treat each actionable BBS handoff as a finite task thread" in source
    assert "Do not ACK an empty waiting-pickup shell just to clear it" in source
    assert "Post checkpoint updates for long-running work" in source
    assert "Fork broad project, policy, incident, or standing-context threads" in source
    assert "acknowledge pickup by posting in the thread" in source
    assert "scripts/bbs_task_lifecycle.py" in source
    assert "scripts/bbs_janitor.py" in source
    assert "Apply only deterministic safe fixes" in source
    assert "Close the loop when the task is complete" in source
    assert "Do not leave old picked-up or waiting-pickup BBS threads open" in source
    assert "Norman and Subprime are the admin-level coordination actors" in source
    assert "NetOps is the network/frontdoor/DNS/Caddy/root-side support owner" in source
    assert "Family/toy-box actors stay isolated from work/private lanes" in source
    assert "GitHub release flow policy:" in source
    assert "GapIntelligence/.github-private" in source
    assert "WebGOAT uses staging -> master." in source
    assert "GAPI uses qa -> main for QA-gated work" in source
    assert "Armitage and control_plane use staging -> main." in source
    assert "scripts/check_release_gitflow.py" in source


def test_launch_template_exposes_opt_in_soul_context_loader() -> None:
    source = _agent_console_launch_source()

    assert "append_soul_context()" in source
    assert "NORMAN_CODEX_SOUL_ENABLED:-0" in source
    assert "NORMAN_CODEX_SOUL_ACTOR" in source
    assert "NORMAN_CODEX_ACTOR" in source
    assert "NORMAN_CODEX_SOUL_IDENTITY_ROOT" in source
    assert "NORMAN_CODEX_SOUL_LOADER" in source
    assert "compose_soul_context.py" in source
    assert "append_soul_context\nPROMPT_SHA256=" in source
    assert 'context="$(python3 "${args[@]}" 2>/dev/null)"' in source
    assert "POLICY_REFRESH_PROMPT=" in source
    assert "Preserve the current session context" in source
    assert 'run_codex resume --last "$POLICY_REFRESH_PROMPT"' in source


def test_norman_launcher_keeps_shared_bbs_policy() -> None:
    template_source = _agent_console_launch_source()
    norman_source = _norman_codex_launch_source()

    assert "Switchboard BBS operating rules:" in norman_source
    assert (
        "A 403 when reading another actor's inbox, including Norman's, is expected"
        in norman_source
    )
    assert (
        "Norman and Subprime are the admin-level coordination actors" in norman_source
    )
    assert "Treat each actionable BBS handoff as a finite task thread" in norman_source
    assert "Do not ACK an empty waiting-pickup shell just to clear it" in norman_source
    assert "Post checkpoint updates for long-running work" in norman_source
    assert (
        "Fork broad project, policy, incident, or standing-context threads"
        in norman_source
    )
    assert "scripts/bbs_task_lifecycle.py" in norman_source
    assert "scripts/bbs_janitor.py" in norman_source
    assert "Apply only deterministic safe fixes" in norman_source
    assert "Close the loop when the task is complete" in norman_source
    assert 'CODEX_PROFILE_ARGS=(--profile-v2 "$STANDARD_PROFILE_V2")' in norman_source
    assert '"${CODEX_PROFILE_ARGS[@]}"' in norman_source
    assert '"${CODEX_SERVICE_TIER_ARGS[@]}"' in norman_source
    assert "GitHub release flow policy:" in norman_source
    assert "GapIntelligence/.github-private" in norman_source
    assert _launch_policy_block(norman_source) == _launch_policy_block(template_source)
    assert "append_soul_context()" in norman_source
    assert 'run_codex resume --last "$POLICY_REFRESH_PROMPT"' in norman_source


def test_launch_policy_includes_hal_non_interference_boundary() -> None:
    template_source = _agent_console_launch_source()
    norman_source = _norman_codex_launch_source()
    template_policy = _launch_policy_block(template_source)

    assert "HAL / desktop non-interference:" in template_policy
    assert "quiet personal desktop and sensitive credential host" in template_policy
    assert "Do not SSH into HAL" in template_policy
    assert "open browser tabs" in template_policy
    assert "take screenshots" in template_policy
    assert "interact with GUI sessions" in template_policy
    assert "HAL credentials are rotating" in template_policy
    assert "smallest approved maintenance action" in template_policy
    assert _launch_policy_block(norman_source) == template_policy


def test_bbs_doctor_checks_live_policy_contract() -> None:
    source = _bbs_doctor_source()

    assert "th_bbs_escalation_contract_20260525" in source
    assert "EXPECTED_ACTOR_COUNT = 31" in source
    assert 'EXPECTED_ADMIN_ACTORS = {"norman", "subprime"}' in source
    assert '"sal"' not in source
    assert "PROMOTED_TUI_ACTORS" in source
    assert "Treat each actionable BBS handoff as a finite task thread" in source
    assert "Fork broad project, policy, incident, or standing-context threads" in source
    assert "scripts/bbs_task_lifecycle.py" in source
    assert "scripts/bbs_janitor.py" in source
    assert "Apply only deterministic safe fixes" in source
    assert "Close the loop when the task is complete" in source
    assert "Do not leave old picked-up or waiting-pickup BBS threads open" in source
    assert "GitHub release flow policy:" in source
    assert "GapIntelligence/.github-private" in source
    assert "scripts/check_release_gitflow.py" in source
    assert '"phoneops": {' in source
    assert '"artmonster": {' in source
    assert '"diamond-roc": {' in source
    assert '"gold-book": {' in source
    assert '"leadership-kpis": {' in source
    assert '"platinum-standard": {' in source
    assert '"uplink": {' in source
    assert '"site": "phones"' in source
    assert '"system": "phoneops"' in source
    assert "--repair-launcher" in source
    assert "--probe-actor" in source
    assert "--actor-env-file" in source
    assert "--probe-grant-revoke" in source
    assert "netops upward grant denied with hint" in source
    assert "promoted TUIs can create Norman escalations" in source
    assert "admin grant/revoke access path" in source


def test_bbs_doctor_parses_actor_filters() -> None:
    module = _load_bbs_doctor()
    doctor = module.Doctor(
        module.parse_args(
            [
                "--actor",
                "castle,dj",
                "--actor",
                "castle",
                "--probe-actor",
                "phoneops,mls",
            ]
        )
    )

    assert doctor.actor_filter == ["castle", "dj"]
    assert doctor.probe_actor_filter == ["phoneops", "mls"]


def test_bbs_doctor_uses_actor_env_file_override(tmp_path) -> None:
    module = _load_bbs_doctor()
    env_file = tmp_path / "norman.env"
    env_file.write_text("SWITCHBOARD_TOKEN=test-token\n", encoding="utf-8")
    doctor = module.Doctor(
        module.parse_args(["--actor-env-file", f"norman={env_file}"])
    )

    assert doctor.token("norman") == "test-token"


def test_bbs_doctor_empty_default_actor_env_does_not_mean_cwd(
    monkeypatch, tmp_path
) -> None:
    module = _load_bbs_doctor()
    monkeypatch.setattr(module, "DEFAULT_ACTOR_ENV_FILE", "")
    env_file = tmp_path / "norman.env"
    env_file.write_text("SWITCHBOARD_TOKEN=dir-token\n", encoding="utf-8")
    doctor = module.Doctor(module.parse_args(["--actor-dir", str(tmp_path)]))

    assert doctor.token("norman") == "dir-token"


def test_bbs_doctor_limits_actor_checks_to_requested_tuis() -> None:
    module = _load_bbs_doctor()
    doctor = module.Doctor(
        module.parse_args(["--actor", "castle,dj", "--probe-escalation"])
    )
    doctor.live_actors = lambda: ["castle", "dj", "phoneops", "norman"]
    calls = []

    def actor_request(actor, method, path, *, payload=None):
        calls.append((actor, method, path, payload))
        return 200, {"ok": True}

    doctor.actor_request = actor_request

    doctor.check_policy_thread_readable()
    read_actors = [actor for actor, method, _path, _payload in calls if method == "GET"]

    doctor.probe_escalation_create()
    create_actors = [
        actor
        for actor, method, path, _payload in calls
        if method == "POST" and path == "/api/v1/threads"
    ]
    cleanup_actors = [
        actor
        for actor, method, path, _payload in calls
        if method == "POST" and path.endswith("/delete")
    ]

    assert read_actors == ["castle", "dj"]
    assert create_actors == ["castle", "dj"]
    assert cleanup_actors == ["norman", "norman"]
    assert doctor.checks[-1].ok is True
    assert doctor.checks[-1].data["checked"] == 2


def test_bbs_doctor_probe_admin_grant_revoke_uses_transient_thread() -> None:
    module = _load_bbs_doctor()
    doctor = module.Doctor(module.parse_args(["--probe-grant-revoke"]))
    calls = []

    def actor_request(actor, method, path, *, payload=None):
        calls.append((actor, method, path, payload))
        if path == "/api/v1/threads":
            return 201, {"ok": True, "thread": {"thread_id": payload["thread_id"]}}
        if path.endswith("/grant"):
            return 200, {"ok": True, "grant": {"grant_id": payload["grant_id"]}}
        if path.endswith("/revoke-grant"):
            return 200, {"ok": True, "revoked": [{"grant_id": payload["grant_id"]}]}
        if method == "GET":
            return 200, {"ok": True, "thread": {"access_grants": []}}
        if path.endswith("/delete"):
            return 200, {"ok": True}
        raise AssertionError(path)

    doctor.actor_request = actor_request

    doctor.probe_admin_grant_revoke()

    paths = [path for _actor, _method, path, _payload in calls]
    assert paths[0] == "/api/v1/threads"
    assert any(path.endswith("/grant") for path in paths)
    assert any(path.endswith("/revoke-grant") for path in paths)
    assert any(path.endswith("/delete") for path in paths)
    assert doctor.checks[-1].ok is True


def test_bbs_doctor_reports_unknown_probe_actor_without_live_request() -> None:
    module = _load_bbs_doctor()
    doctor = module.Doctor(
        module.parse_args(["--probe-escalation", "--probe-actor", "missing-tui"])
    )

    def actor_request(*_args, **_kwargs):
        raise AssertionError("unknown actors should fail before live requests")

    doctor.actor_request = actor_request

    doctor.probe_escalation_create()

    check = doctor.checks[-1]
    assert check.ok is False
    assert "missing-tui: not a promoted TUI actor" in check.detail
    assert check.data["checked"] == 0


def test_bbs_doctor_reports_check_exceptions_without_traceback(
    tmp_path, capsys
) -> None:
    module = _load_bbs_doctor()
    doctor = module.Doctor(
        module.parse_args(
            [
                "--actor-dir",
                str(tmp_path),
                "--bot-directory",
                str(tmp_path / "missing-bots.json"),
                "--json",
            ]
        )
    )

    def fail() -> None:
        raise PermissionError("blocked actor env")

    doctor.check_prompt_drift = fail
    doctor.check_health = lambda: doctor.add("bbs health clean", True)
    doctor.check_capabilities = lambda: doctor.add(
        "bbs capabilities authority model", True
    )
    doctor.check_policy_thread_readable = lambda: doctor.add(
        "policy thread readable by live actors", True
    )
    doctor.check_grant_denial_hint = lambda: doctor.add(
        "netops upward grant denied with hint", True
    )

    exit_code = doctor.run()
    doctor.emit(exit_code)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Traceback" not in output
    assert '"ok": false' in output
    assert "PermissionError: blocked actor env" in output


def test_agent_console_bbs_summary_is_unconfigured_without_bbs_env(
    monkeypatch,
) -> None:
    for key in (
        "NORMAN_CODEX_BBS_URL",
        "HOUSEBOT_CODEX_BBS_URL",
        "SWITCHBOARD_URL",
        "NORMAN_CODEX_BBS_TOKEN",
        "HOUSEBOT_CODEX_BBS_TOKEN",
        "SWITCHBOARD_TOKEN",
        "NORMAN_CODEX_BBS_TOKEN_FILE",
        "HOUSEBOT_CODEX_BBS_TOKEN_FILE",
        "SWITCHBOARD_TOKEN_FILE",
        "NORMAN_CODEX_BBS_ENV_FILE",
        "HOUSEBOT_CODEX_BBS_ENV_FILE",
        "SWITCHBOARD_ENV_FILE",
        "NORMAN_CODEX_BBS_SUMMARY_ENABLED",
        "HOUSEBOT_CODEX_BBS_SUMMARY_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    module = _load_agent_console_web()

    summary = module.current_bbs_summary(force=True)

    assert summary["schema"] == "norman.tui.bbs-summary.v1"
    assert summary["state"] == "unconfigured"
    assert summary["counts"]["inbox"] == 0
    assert summary["top_threads"] == []


def test_agent_console_bbs_summary_counts_threads_without_leaking_token(
    monkeypatch,
) -> None:
    for key in (
        "NORMAN_CODEX_BBS_URL",
        "NORMAN_CODEX_BBS_TOKEN",
        "NORMAN_CODEX_BBS_TOKEN_FILE",
        "NORMAN_CODEX_BBS_ENV_FILE",
        "NORMAN_CODEX_BBS_ACTOR",
        "NORMAN_CODEX_BBS_SUMMARY_ENABLED",
        "HOUSEBOT_CODEX_BBS_URL",
        "HOUSEBOT_CODEX_BBS_TOKEN",
        "HOUSEBOT_CODEX_BBS_TOKEN_FILE",
        "HOUSEBOT_CODEX_BBS_ENV_FILE",
        "HOUSEBOT_CODEX_BBS_ACTOR",
        "HOUSEBOT_CODEX_BBS_SUMMARY_ENABLED",
        "SWITCHBOARD_URL",
        "SWITCHBOARD_TOKEN",
        "SWITCHBOARD_TOKEN_FILE",
        "SWITCHBOARD_ENV_FILE",
        "SWITCHBOARD_ACTOR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NORMAN_CODEX_BBS_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_BBS_URL", "http://bbs.local")
    monkeypatch.setenv("NORMAN_CODEX_BBS_TOKEN", "secret-bbs-token")
    monkeypatch.setenv("NORMAN_CODEX_BBS_ACTOR", "panelbot")
    module = _load_agent_console_web()
    calls: list[tuple[str, str]] = []

    def fake_bbs_request_json(
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        assert token == "secret-bbs-token"
        calls.append((method, path))
        if method == "POST" and path == "/api/v1/actors/panelbot/heartbeat":
            assert payload
            assert payload["actor"] == "panelbot"
            assert payload["agent"]
            assert payload["host"]
            return {"ok": True, "heartbeat": payload}
        if path == "/api/v1/me":
            return {
                "ok": True,
                "actor": "panelbot",
                "bot": {
                    "heartbeat_ok": True,
                    "heartbeat_age_seconds": 12,
                },
                "inbox_count": 2,
                "inbox": [
                    {
                        "thread_id": "th_urgent",
                        "title": "work-special VM wedged",
                        "priority": "urgent",
                        "status": "open",
                        "owner": "netops",
                        "last_message_at": "2000-01-01T00:00:00Z",
                        "loop": {
                            "state": "waiting_pickup",
                            "label": "Waiting for pickup",
                            "owner_heartbeat": "ok",
                            "owner_heartbeat_age_seconds": 5,
                        },
                    },
                    {
                        "thread_id": "th_high",
                        "title": "TUI route slow",
                        "priority": "high",
                        "status": "open",
                        "owner": "panelbot",
                        "last_message_at": "2000-01-01T00:00:00Z",
                        "loop": {"state": "active"},
                    },
                ],
            }
        if path == "/api/v1/threads":
            return {
                "ok": True,
                "threads": [
                    {
                        "thread_id": "th_urgent",
                        "title": "work-special VM wedged",
                        "priority": "urgent",
                        "status": "open",
                        "owner": "netops",
                        "last_message_at": "2000-01-01T00:00:00Z",
                        "loop": {"state": "waiting_pickup"},
                    },
                    {
                        "thread_id": "th_high",
                        "title": "TUI route slow",
                        "priority": "high",
                        "status": "open",
                        "owner": "panelbot",
                        "last_message_at": "2000-01-01T00:00:00Z",
                        "loop": {"state": "active"},
                    },
                    {
                        "thread_id": "th_stale",
                        "title": "Old picked-up BBS task",
                        "priority": "normal",
                        "status": "open",
                        "owner": "netops",
                        "last_message_at": "2000-01-01T00:00:00Z",
                        "loop": {"state": "picked_up", "picked_up_by": "netops"},
                    },
                ],
            }
        if path == "/api/v1/bots":
            return {
                "ok": True,
                "bots": [
                    {
                        "actor": "netops",
                        "heartbeat_required": True,
                        "heartbeat_ok": True,
                        "token_present": True,
                    },
                    {
                        "actor": "panelbot",
                        "heartbeat_required": True,
                        "heartbeat_ok": True,
                        "token_present": True,
                    },
                ],
            }
        return {
            "ok": False,
            "error": "unexpected_path",
            "path": path,
        }

    monkeypatch.setattr(module, "bbs_request_json", fake_bbs_request_json)

    summary = module.current_bbs_summary(force=True)
    rendered = json.dumps(summary, sort_keys=True)

    assert calls[0] == ("POST", "/api/v1/actors/panelbot/heartbeat")
    assert calls[1] == ("GET", "/api/v1/me")
    assert summary["state"] == "alert"
    assert summary["tone"] == "alert"
    assert summary["actor"] == "panelbot"
    assert summary["heartbeat_ok"] is True
    assert summary["counts"] == {
        "inbox": 2,
        "urgent": 1,
        "high": 1,
        "actionable_urgent": 1,
        "actionable_high": 1,
        "waiting_pickup": 1,
        "picked_up": 0,
        "missing_context": 0,
        "owner_offline": 0,
        "owner_stale": 0,
        "stale": 1,
    }
    assert summary["top_threads"][0]["thread_id"] == "th_urgent"
    assert summary["top_threads"][0]["activity"].startswith(
        "Owner netops needs pickup ACK"
    )
    assert summary["top_threads"][0]["lifecycle"] == "needs_ack"
    assert summary["top_threads"][0]["lifecycle_label"] == "needs owner pickup"
    assert (
        "Owner TUI should ACK only if picking up"
        in summary["top_threads"][0]["next_action"]
    )
    assert (
        "bbs_task_lifecycle.py ack --actor panelbot th_urgent"
        in summary["top_threads"][0]["ack_command"]
    )
    assert (
        "bbs_task_lifecycle.py blocked --actor panelbot th_urgent"
        in summary["top_threads"][0]["blocked_command"]
    )
    assert summary["top_threads"][0]["tone"] == "alert"
    assert summary["activity"].startswith("Owner netops needs pickup ACK")
    assert summary["handoff"]["state"] == "needs_ack"
    assert summary["handoff"]["tone"] == "ack"
    assert summary["handoff"]["ack_semantics"] == "manual_pickup_ack"
    assert summary["handoff"]["needs_ack"] == 1
    assert summary["handoff"]["thread_id"] == "th_urgent"
    assert (
        "Owner TUI 'netops' should ACK only if picking up"
        in summary["handoff"]["next_action"]
    )
    assert (
        "bbs_task_lifecycle.py ack --actor panelbot th_urgent"
        in summary["handoff"]["ack_command"]
    )
    assert (
        "bbs_task_lifecycle.py fork --actor panelbot th_urgent"
        in summary["handoff"]["fork_command_hint"]
    )
    assert (
        "bbs_task_lifecycle.py done --actor panelbot th_urgent"
        in summary["handoff"]["done_command"]
    )
    assert (
        "bbs_task_lifecycle.py blocked --actor panelbot th_urgent"
        in summary["handoff"]["blocked_command"]
    )
    prompt_context = module.bbs_handoff_prompt_context(summary)
    assert "BBS handoff alert:" in prompt_context
    assert "From: Switchboard BBS." in prompt_context
    assert "Why:" in prompt_context
    assert "this console actor panelbot" in prompt_context
    assert "owner TUI netops" in prompt_context
    assert "Choose one:" in prompt_context
    assert "Fine print:" in prompt_context
    assert "ACK means the actor in the command is taking ownership" in prompt_context
    assert "ACK helper:" in prompt_context
    assert "FORK helper:" in prompt_context
    assert "DONE helper:" in prompt_context
    assert "BLOCKED helper:" in prompt_context
    assert summary["janitor"]["state"] == "review"
    assert summary["janitor"]["open_thread_count"] == 3
    assert summary["janitor"]["review_count"] == 2
    assert summary["janitor"]["safe_count"] == 0
    assert summary["janitor"]["actions"][0]["action"] == "stale_picked_up"
    assert any(
        action["action"] == "unacked_handoff"
        for action in summary["janitor"]["actions"]
    )
    assert "secret-bbs-token" not in rendered


def test_bbs_handoff_summary_flags_empty_waiting_pickup_context() -> None:
    module = _load_agent_console_web()

    summary = module.summarize_bbs_payload(
        {
            "actor": "netops",
            "bot": {"heartbeat_ok": True, "heartbeat_age_seconds": 4},
            "inbox_count": 1,
            "inbox": [
                {
                    "thread_id": "th_empty_shell",
                    "title": "empty waiting shell",
                    "priority": "normal",
                    "status": "open",
                    "owner": "netops",
                    "message_count": 0,
                    "last_message_at": "",
                    "loop": {"state": "waiting_pickup"},
                }
            ],
        }
    )

    thread = summary["top_threads"][0]
    assert summary["counts"]["waiting_pickup"] == 1
    assert summary["counts"]["missing_context"] == 1
    assert thread["lifecycle"] == "missing_context"
    assert thread["lifecycle_label"] == "missing context"
    assert thread["tone"] == "review"
    assert thread["has_handoff_context"] is False
    assert thread["handoff_contract_state"] == "missing_context"
    assert "Creator should add body/evidence before owner ACKs" in thread["next_action"]
    assert summary["handoff"]["state"] == "review"
    assert summary["handoff"]["tone"] == "review"
    assert summary["handoff"]["missing_context"] == 1
    prompt_context = module.bbs_handoff_prompt_context(summary)
    assert "Handoff contract: missing body/evidence" in prompt_context
    assert "Do not ACK this shell just to clear it" in prompt_context


def test_bbs_handoff_summary_ignores_terminal_unacked_janitor_action() -> None:
    module = _load_agent_console_web()

    handoff = module._bbs_handoff_summary(
        [
            {
                "thread_id": "th_done",
                "title": "Already blocked",
                "owner": "subprime",
                "lifecycle": "blocked",
                "next_action": "Thread is blocked.",
            }
        ],
        {
            "actions": [
                {
                    "action": "unacked_handoff",
                    "thread_id": "th_done",
                    "title": "Already blocked",
                    "owner": "subprime",
                    "safety": "review",
                    "reason": "Old unacked handoff action.",
                }
            ]
        },
    )

    assert handoff["state"] == "clear"
    assert handoff["needs_ack"] == 0
    assert handoff["review"] == 0
    assert handoff["thread_id"] == ""


def test_bbs_handoff_summary_ignores_terminal_janitor_action_status() -> None:
    module = _load_agent_console_web()

    handoff = module._bbs_handoff_summary(
        [],
        {
            "actions": [
                {
                    "action": "unacked_handoff",
                    "thread_id": "th_blocked_elsewhere",
                    "title": "Already blocked elsewhere",
                    "owner": "subprime",
                    "status": "blocked",
                    "safety": "review",
                    "reason": "Old unacked handoff action for a blocked task.",
                }
            ]
        },
    )

    assert handoff["state"] == "clear"
    assert handoff["needs_ack"] == 0
    assert handoff["review"] == 0
    assert handoff["thread_id"] == ""


def test_sentinel_ignores_blocked_high_priority_bbs_thread(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_SENTINEL_MODE", "observe_only")
    module = _load_agent_console_web()
    monkeypatch.setattr(module, "now_ts", lambda: 1_000)
    snapshot = {
        "pending": False,
        "queue_depth": 0,
        "web_worker_alive": False,
        "model_process_alive": False,
        "active_child_pid": 0,
        "bbs": {
            "counts": {
                "urgent": 0,
                "high": 1,
            },
            "handoff": {
                "state": "clear",
                "needs_ack": 0,
                "owner_attention": 0,
            },
            "top_threads": [
                {
                    "thread_id": "th_already_blocked",
                    "priority": "high",
                    "status": "blocked",
                    "lifecycle": "blocked",
                    "loop_state": "picked_up",
                }
            ],
        },
    }

    sentinel = module.build_sentinel_state(
        snapshot,
        {"state": "idle", "signals": []},
    )

    assert module._sentinel_bbs_count(snapshot, "high") == 0
    assert sentinel["state"] == "healthy_idle"
    assert sentinel["severity"] == "quiet_log"
    assert sentinel["evidence"]["bbs_urgent_count"] == 0
    assert "bbs_urgent" not in sentinel["reason_codes"]


def test_agent_console_bbs_summary_uses_canonical_norman_env(
    monkeypatch, tmp_path
) -> None:
    for key in (
        "NORMAN_CODEX_BBS_URL",
        "NORMAN_CODEX_BBS_TOKEN",
        "NORMAN_CODEX_BBS_TOKEN_FILE",
        "NORMAN_CODEX_BBS_ENV_FILE",
        "NORMAN_CODEX_BBS_ACTOR",
        "NORMAN_CODEX_BBS_SUMMARY_ENABLED",
        "HOUSEBOT_CODEX_BBS_URL",
        "HOUSEBOT_CODEX_BBS_TOKEN",
        "HOUSEBOT_CODEX_BBS_TOKEN_FILE",
        "HOUSEBOT_CODEX_BBS_ENV_FILE",
        "HOUSEBOT_CODEX_BBS_ACTOR",
        "HOUSEBOT_CODEX_BBS_SUMMARY_ENABLED",
        "SWITCHBOARD_URL",
        "SWITCHBOARD_TOKEN",
        "SWITCHBOARD_TOKEN_FILE",
        "SWITCHBOARD_ENV_FILE",
        "SWITCHBOARD_ACTOR",
    ):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / "switchboard-bbs.env"
    env_file.write_text("SWITCHBOARD_TOKEN=env-file-token\n", encoding="utf-8")
    monkeypatch.setenv("NORMAN_CODEX_BBS_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_BBS_URL", "http://bbs.local")
    monkeypatch.setenv("NORMAN_CODEX_BBS_ENV_FILE", str(env_file))
    monkeypatch.setenv("NORMAN_CODEX_BBS_ACTOR", "gold-book")
    module = _load_agent_console_web()

    def fake_bbs_request_json(
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        assert token == "env-file-token"
        if method == "POST":
            assert path == "/api/v1/actors/gold-book/heartbeat"
            assert payload
            assert payload["actor"] == "gold-book"
            return {"ok": True}
        if path == "/api/v1/me":
            return {
                "ok": True,
                "actor": "gold-book",
                "bot": {"heartbeat_ok": True, "heartbeat_age_seconds": 1},
                "inbox": [],
                "inbox_count": 0,
            }
        if path == "/api/v1/threads":
            return {"ok": True, "threads": []}
        if path == "/api/v1/bots":
            return {
                "ok": True,
                "bots": [
                    {
                        "actor": "gold-book",
                        "heartbeat_required": True,
                        "heartbeat_ok": True,
                        "token_present": True,
                    }
                ],
            }
        return {"ok": False, "error": "unexpected_path", "path": path}

    monkeypatch.setattr(module, "bbs_request_json", fake_bbs_request_json)

    summary = module.current_bbs_summary(force=True)

    assert module.BBS_SUMMARY_URL == "http://bbs.local"
    assert module.BBS_SUMMARY_ACTOR == "gold-book"
    assert summary["state"] == "ok"
    assert summary["actor"] == "gold-book"


def test_agent_console_bbs_summary_survives_heartbeat_timeout(monkeypatch) -> None:
    for key in (
        "NORMAN_CODEX_BBS_URL",
        "NORMAN_CODEX_BBS_TOKEN",
        "NORMAN_CODEX_BBS_TOKEN_FILE",
        "NORMAN_CODEX_BBS_ENV_FILE",
        "NORMAN_CODEX_BBS_ACTOR",
        "NORMAN_CODEX_BBS_SUMMARY_ENABLED",
        "HOUSEBOT_CODEX_BBS_URL",
        "HOUSEBOT_CODEX_BBS_TOKEN",
        "HOUSEBOT_CODEX_BBS_TOKEN_FILE",
        "HOUSEBOT_CODEX_BBS_ENV_FILE",
        "HOUSEBOT_CODEX_BBS_ACTOR",
        "HOUSEBOT_CODEX_BBS_SUMMARY_ENABLED",
        "SWITCHBOARD_URL",
        "SWITCHBOARD_TOKEN",
        "SWITCHBOARD_TOKEN_FILE",
        "SWITCHBOARD_ENV_FILE",
        "SWITCHBOARD_ACTOR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NORMAN_CODEX_BBS_SUMMARY_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_BBS_URL", "http://bbs.local")
    monkeypatch.setenv("NORMAN_CODEX_BBS_TOKEN", "secret-bbs-token")
    monkeypatch.setenv("NORMAN_CODEX_BBS_ACTOR", "panelbot")
    module = _load_agent_console_web()
    calls: list[tuple[str, str]] = []

    def fake_bbs_request_json(
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        calls.append((method, path))
        assert token == "secret-bbs-token"
        if method == "POST":
            assert timeout_seconds == 3.0
            raise TimeoutError("heartbeat slow")
        if path == "/api/v1/me":
            return {
                "ok": True,
                "actor": "panelbot",
                "bot": {"heartbeat_ok": False},
                "inbox": [],
                "inbox_count": 0,
            }
        if path == "/api/v1/threads":
            return {"ok": True, "threads": []}
        if path == "/api/v1/bots":
            return {"ok": True, "bots": []}
        return {"ok": False, "error": "unexpected_path", "path": path}

    monkeypatch.setattr(module, "bbs_request_json", fake_bbs_request_json)

    summary = module.current_bbs_summary(force=True)

    assert calls[0] == ("POST", "/api/v1/actors/panelbot/heartbeat")
    assert calls[1] == ("GET", "/api/v1/me")
    assert summary["state"] == "unknown"
    assert summary["actor"] == "panelbot"


def test_agent_console_renders_bbs_summary_outside_conversation() -> None:
    source = _agent_console_web_source()

    assert 'parsed.path == "/api/bbs/summary"' in source
    assert "def publish_bbs_heartbeat" in source
    assert '"/api/v1/actors/{quote(BBS_SUMMARY_ACTOR)}/heartbeat"' in source
    assert 'id="bbs-summary-card"' in source
    assert 'id="bbs-icon-tray"' in source
    assert 'id="bbs-summary-activity"' in source
    assert 'document.getElementById("bbs-summary-card")' in source
    assert 'document.getElementById("bbs-icon-tray")' in source
    assert "norman.tui.bbs-janitor-summary.v1" in source
    assert "function renderBbsSummary(snapshot) {{" in source
    assert "function bbsMissingContextCount(counts, handoff, threads) {{" in source
    assert "function bbsIconItems(snapshot, bbs, handoff, janitor, threads" in source
    assert "function bbsActorDisplay(value) {{" in source
    assert "function bbsRoleLine(bbs, handoff) {{" in source
    assert "function bbsOwnerActionLine(bbs, handoff, firstThread = {{}}) {{" in source
    assert "shown on ${{actorLabel}} · owner ${{ownerLabel}}" in source
    assert "needs to ACK pickup; ${{actorLabel}} is only showing the alert." in source
    assert (
        "function bbsAttentionQueueItems(bbs, handoff, janitor, threads, janitorActions"
        in source
    )
    assert "function bbsAttentionLabelForThread(thread) {{" in source
    assert "function bbsLifecycleActions(item) {{" in source
    assert "function appendBbsLifecycleActions(row, item) {{" in source
    assert "function bbsLifecyclePrompt(item, action) {{" in source
    assert 'row.className = "bbs-thread-row bbs-attention-row";' in source
    assert '"Needs owner"' in source
    assert '"Needs context"' in source
    assert '"Close loop"' in source
    assert '"Owner offline"' in source
    assert '"Janitor review"' in source
    assert ".bbs-thread-row.bbs-attention-row" in source
    assert ".bbs-summary-card::after" in source
    assert ".bbs-icon-tray" in source
    assert ".bbs-icon.spin" in source
    assert "@keyframes bbsIconFlash" in source
    assert ".bbs-thread-row::after" in source
    assert "@keyframes attentionTonePulse" in source
    assert ".bbs-thread-actions" in source
    assert ".bbs-lifecycle-button" in source
    assert 'button.dataset.bbsAction = String(action.action || "");' in source
    assert "Prepare to run this BBS lifecycle action" in source
    assert "appendBbsLifecycleActions(row, item)" in source
    assert "appendBbsLifecycleActions(row, action)" in source
    assert "appendBbsLifecycleActions(row, thread)" in source
    assert "janitor.review_count" in source
    assert "const handoff = bbs && typeof bbs.handoff ===" in source
    assert "normalizeBbsTone(handoff.tone || bbs.tone || bbs.state)" in source
    assert "bbsKpiTone(bbs.tone || handoff.tone || bbs.state)" in source
    assert "thread.lifecycle_label || thread.loop_label" in source
    assert "next:" in source
    assert "handoff.ack_command" in source
    assert "handoff.blocked_command" in source
    assert "thread.fork_command_hint" in source
    assert "attentionThreadIds" in source
    assert "BBS loop needs attention." in source
    assert "Creator should add body/evidence before owner ACKs." in source


def test_agent_console_surfaces_bbs_activity_inline() -> None:
    source = _agent_console_web_source()

    assert "function bbsOutboundSignal(snapshot) {{" in source
    assert "function bbsInlineSignal(snapshot) {{" in source
    assert "function bbsToastSignal(snapshot) {{" in source
    assert ".notice-chip.ack" in source
    assert ".notice-chip::after" in source
    assert ".toast.ack" in source
    assert ".toast::after" in source
    assert "--tone-alt" in source
    assert 'if (tone === "ack") return "↓";' in source
    assert "function syncBbsNotifications(prevSnapshot, nextSnapshot) {{" in source
    assert "syncBbsNotifications(prev, snapshot);" in source
    assert "const bbsSignal = bbsInlineSignal(snapshot);" in source
    assert (
        "const missingContext = bbsMissingContextCount(counts, handoff, topThreads);"
        in source
    )
    assert (
        "? `${{bbsActorDisplay(handoff.owner) || formatCount(needsAck)}} ACK`" in source
    )
    assert "bbsOwnerActionLine(bbs, handoff, first)" in source
    assert "const outboundBbsSignal = bbsOutboundSignal(snapshot);" in source
    assert "const previous = bbsToastSignal(prevSnapshot);" in source
    assert "const next = bbsToastSignal(nextSnapshot);" in source
    assert "const isHardAttention = (" in source
    assert (
        "const isHandoffAttention = needsAck > 0 || waiting > 0 || missingContext > 0"
        in source
    )
    assert "BBS handoff missing context" in source
    assert "BBS conversation active" in source
    assert '"callback_url": (' in source
    assert 'params.get("relay_callback_url")' in source
    assert "relay_callback=relay_callback" in source
    assert 'status="running"' in source
    assert 'status="queued"' in source
    assert '? "ack"' in source
    assert '? "working"' in source
    assert "janitorReview" in source
    assert "janitorKey" in source
    assert "needsAck" in source
    assert "handoffActivity" in source
    assert "BBS clear" in source
    assert "BBS in/out" in source
    assert "BBS outbound" in source
    assert "Outbound BBS queued" in source
    assert ".notice-chip.bbs" in source
    assert ".toast.bbs" in source
    assert 'id: "bbs"' in source


def test_bbs_doctor_systemd_units_are_read_only_and_triggered() -> None:
    service = _systemd_unit_source("norman-bbs-doctor.service")
    timer = _systemd_unit_source("norman-bbs-doctor.timer")
    path = _systemd_unit_source("norman-bbs-doctor.path")

    assert (
        "ExecStart=/usr/bin/python3 /home/kristopher/code/norman/scripts/bbs_doctor.py --repair-launcher"
        in service
    )
    assert "--probe-escalation" not in service
    assert "OnUnitActiveSec=15min" in timer
    assert "Persistent=true" in timer
    assert "scripts/norman_codex_launch.sh" in path
    assert "scripts/agent_console_template/agent_console_launch.sh" in path
    assert "SWITCHBOARD_BOT_DIRECTORY.json" in path
    assert "switchboard_bbs_service.py" in path


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


def test_control_plane_prompt_has_emerald_canopy_contract() -> None:
    control_plane_prompt = _agent_prompt_template_source("control-plane.txt")
    emerald_fragment = _agent_prompt_template_source("emerald-canopy.txt")

    assert "Emerald Canopy execution policy:" in emerald_fragment
    assert "Emerald Canopy execution policy:" in control_plane_prompt
    assert "Use connected mode as the default for Control Plane TUI work" in (
        control_plane_prompt
    )
    assert "Use benchmark mode for CP/KPI/Gold Book model comparisons" in (
        control_plane_prompt
    )
    assert "route, model, token use, estimated cost, elapsed time, outcome" in (
        control_plane_prompt
    )
    assert "Use deploy mode before public routing" in control_plane_prompt
    assert "Use air_gapped mode only for local repo-only work" in control_plane_prompt
    assert "Never revert unrelated user changes" in control_plane_prompt
    assert "Model ladder and runbook routing policy:" in control_plane_prompt
    assert "separate frame/verify from runbook work" in control_plane_prompt
    assert "Prefer Bedrock routes for Control Plane when available" in (
        control_plane_prompt
    )
    assert "Use direct OpenAI only" in control_plane_prompt
    assert "Use GPT-5.4 on Bedrock as the default strong verifier candidate" in (
        control_plane_prompt
    )
    assert "cheaper worker/scout lanes for eligible runbook routing" in (
        control_plane_prompt
    )
    assert "priority/fast only when the operator needs an urgent response" in (
        control_plane_prompt
    )
    assert "GPT-5.5 xhigh as a reference/verifier lane" in control_plane_prompt


def test_code_authoring_prompts_have_role_specific_emerald_canopy_contracts() -> None:
    diamond_roc_prompt = _agent_prompt_template_source("diamond-roc.txt")
    scout_prompt = _agent_prompt_template_source("scout.txt")

    assert "Emerald Canopy execution policy:" in diamond_roc_prompt
    assert "Use connected mode as the default for Diamond Roc service work" in (
        diamond_roc_prompt
    )
    assert "Use air_gapped mode only for local repo-only edits" in (diamond_roc_prompt)
    assert "Use deploy mode before public routing" in diamond_roc_prompt
    assert "Use benchmark mode only when comparing model behavior" in (
        diamond_roc_prompt
    )
    assert "Never revert unrelated user changes" in diamond_roc_prompt

    assert "You are Scout/Ranger, the work research collection lane." in scout_prompt
    assert "Do not take implementation, deploy, service restart" in scout_prompt
    assert "Emerald Canopy execution policy:" not in scout_prompt


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
    assert 'data-value="off">Silent</button>' in source
    assert "frequency: 118" in source
    assert "duration: 3.1" in source
    assert (
        "const AGENT_COMPLETION_BELL_PROFILE = buildAgentCompletionBellProfile();"
        in source
    )
    assert "if (AGENT_COMPLETION_BELL_PROFILE) {{" in source
    assert 'const profile = key === "agent"' in source
    assert "function audioQuietReason(options = {{}})" in source
    assert 'document.visibilityState !== "visible"' in source
    assert "if (audioQuietReason(options)) {{" in source
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
    assert "function extractClosingChoiceOptions(body, maxChoices = 4) {{" in source
    assert "function closingChoiceReplyDescriptors(body, maxChoices = 4) {{" in source
    assert "label: `#${{choice.ordinal}}`" in source
    assert "prompt: `I choose option ${{choice.ordinal}}: ${{choice.text}}`" in source
    assert 'button.dataset.choiceAction = "true";' in source
    assert (
        'const shouldOfferProceed = scoreReplyActionKind("proceed", sourcePrompt, body) >= 40;'
        in source
    )
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
    assert (
        'ack.state === "queued" ? "Outbound BBS queued" : "Outbound BBS picked up"'
        in source
    )
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
    assert(sendLabel.textContent.trim() === "Queue prompt", `send button does not show Queue prompt: ${sendLabel.textContent.trim()}`);
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
            str(_jsdom_module_path()),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_rendered_console_keeps_table_cartouches_after_javascript_render() -> None:
    module = _load_agent_console_web()
    module.ensure_session = lambda: None
    module.current_snapshot = lambda: {
        "pending": False,
        "thread_id": "thread-cartouche-demo",
        "updated_at": 1770000000,
        "services": [],
        "last_prompt": "Show the TUI cartouches.",
        "last_response": "Done.",
        "last_error": "",
        "pane": "[pane unavailable]",
        "logs": "[no journal output]",
        "history": [
            {
                "prompt": "Show the TUI cartouches.",
                "response": (
                    "| Name | Type |\n"
                    "| --- | --- |\n"
                    "| Control Plane | tui |\n"
                    "| Phone Ops | tui |\n"
                    "| CloudAgent | tui |\n"
                    "| Uplink | tui |\n"
                    "| Subprime | service |\n"
                    "| Norman Ops | service |\n"
                    "| Switchboard | service |\n"
                ),
                "started_at": 1770000000,
                "finished_at": 1770000010,
                "speed": "balanced",
                "detail": 3,
                "attachments": [],
            }
        ],
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

    temp_dir = Path(tempfile.mkdtemp())
    html_path = temp_dir / "console.html"
    html_path.write_text(rendered, encoding="utf-8")
    node_path = temp_dir / "assert_table_cartouches.js"
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

function cartoucheLabel(node) {
  const label = node.querySelector(".entity-cartouche__label");
  return (label || node).textContent.trim();
}

function cartoucheFor(label) {
  return Array.from(dom.window.document.querySelectorAll(".message-body table .entity-cartouche"))
    .find((node) => cartoucheLabel(node) === label);
}

setTimeout(() => {
  try {
    assert(errors.length === 0, `jsdom errors: ${errors.join("\\n")}`);
    const expectedTuis = ["Control Plane", "Phone Ops", "CloudAgent", "Uplink"];
    for (const label of expectedTuis) {
      const node = cartoucheFor(label);
      assert(node, `missing cartouche for ${label}`);
      assert(node.dataset.kind === "tui", `${label} rendered as ${node.dataset.kind}`);
    }
    for (const label of ["Subprime", "Norman Ops"]) {
      const node = cartoucheFor(label);
      assert(node, `missing cartouche for ${label}`);
      assert(node.dataset.kind === "service", `${label} rendered as ${node.dataset.kind}`);
      assert(node.dataset.aliasFor === "Switchboard", `${label} alias target is ${node.dataset.aliasFor}`);
    }
    const switchboard = cartoucheFor("Switchboard");
    assert(switchboard, "missing cartouche for Switchboard");
    assert(switchboard.dataset.kind === "service", `Switchboard rendered as ${switchboard.dataset.kind}`);
    process.exit(0);
  } catch (error) {
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }
}, 80);
        """.strip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "node",
            str(node_path),
            str(html_path),
            str(_jsdom_module_path()),
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


def test_template_recovers_interrupted_attachment_upload_responses() -> None:
    source = _agent_console_web_source()

    assert "function recoverAttachmentUploadStatus(previousDraftSignature) {{" in source
    assert (
        "const recovered = await recoverAttachmentUploadStatus(previousDraftSignature);"
        in source
    )
    assert "Upload response was interrupted;" in source
    assert "function applyDraftAttachmentProtection(snapshot) {{" in source
    assert "snapshotReferencesAttachmentTokens(snapshot, protectedTokens)" in source
    assert "clearDraftAttachmentProtection();" in source


def test_template_suppresses_tailnet_prime_heartbeat_on_non_tailnet_pages() -> None:
    source = _agent_console_web_source()

    assert 'targetHost.endsWith(".tail94915.ts.net")' in source
    assert '!currentHost.endsWith(".tail94915.ts.net")' in source
    assert 'return "";' in source


def test_template_exposes_attachment_size_limit_before_uploading() -> None:
    module = _load_agent_console_web()
    source = _agent_console_web_source()

    assert module.MAX_ATTACHMENT_BYTES == 128 * 1024 * 1024
    assert "AGENT_CONSOLE_MAX_ATTACHMENT_BYTES" in source
    assert "NORMAN_CODEX_MAX_ATTACHMENT_BYTES" in source
    assert "const MAX_ATTACHMENT_BYTES =" in source
    assert "Number(file.size || 0) > MAX_ATTACHMENT_BYTES" in source
    assert 'attachmentUploadUrl("/api/attachment/upload"' in source
    assert "body: file" in source
    assert "data_b64: encoded" not in source
    assert (
        "is too large (${{humanSize(file.size)}}; max ${{humanSize(MAX_ATTACHMENT_BYTES)}})"
        in source
    )


def test_template_attachment_size_limit_prefers_neutral_env(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_CONSOLE_MAX_ATTACHMENT_BYTES", str(96 * 1024 * 1024))
    monkeypatch.setenv("NORMAN_CODEX_MAX_ATTACHMENT_BYTES", str(64 * 1024 * 1024))

    module = _load_agent_console_web()

    assert module.MAX_ATTACHMENT_BYTES == 96 * 1024 * 1024


def test_template_attachment_size_limit_keeps_legacy_env_fallback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENT_CONSOLE_MAX_ATTACHMENT_BYTES", raising=False)
    monkeypatch.delenv("NORMAN_CODEX_MAX_ATTACHMENT_BYTES", raising=False)
    monkeypatch.setenv("HOUSEBOT_CODEX_MAX_ATTACHMENT_BYTES", str(64 * 1024 * 1024))

    module = _load_agent_console_web()

    assert module.MAX_ATTACHMENT_BYTES == 64 * 1024 * 1024


def test_template_surfaces_composer_local_attachment_feedback() -> None:
    source = _agent_console_web_source()

    assert 'id="composer-feedback"' in source
    assert '.composer-feedback[data-tone="error"] {{' in source
    assert "var(--ok)" not in source
    assert "composerFeedbackTimer: 0" in source
    assert 'composerFeedback: document.getElementById("composer-feedback")' in source
    assert (
        'function setComposerFeedback(message, tone = "info", options = {{}}) {{'
        in source
    )
    assert "function showComposerFeedbackError(message) {{" in source
    assert 'setComposerFeedback(waitingText, "info")' in source
    assert (
        'setComposerFeedback(stagedText, "success", {{ timeoutMs: 10000 }})' in source
    )
    assert 'attachmentUploadUrl("/api/attachment/upload"' in source
    assert "request failed (${{res.status}})" in source
    assert "showComposerFeedbackError(`Remove failed: ${{err.message}}`)" in source
    assert "showComposerFeedbackError(`Paste failed: ${{err.message}}`)" in source
    assert "showComposerFeedbackError(`Drop failed: ${{err.message}}`)" in source
    assert "showComposerFeedbackError(`Upload failed: ${{err.message}}`)" in source


def test_template_surfaces_active_work_and_blocks_duplicate_queue_submit() -> None:
    source = _agent_console_web_source()

    assert 'id="composer-active-work"' in source
    assert 'id="composer-safety-rail"' in source
    assert (
        'composerSafetyRail: document.getElementById("composer-safety-rail")' in source
    )
    assert (
        'composerActiveWork: document.getElementById("composer-active-work")' in source
    )
    assert ".composer.is-active-run .composer-input-shell {{" in source
    assert ".composer.is-active-run .composer-input-shell::after {{" in source
    assert '.composer-safety-rail[data-risk="danger"] {{' in source
    assert "function promptSafetyAssessment(message, attachments = []) {{" in source
    assert "function armPromptSafety(assessment) {{" in source
    assert "High-impact prompt armed briefly" in source
    assert "document.body.dataset.safetyAlert" in source
    assert "@keyframes topbarSafetyPulse {{" in source
    assert "@keyframes activeComposerPulse {{" in source
    assert "@keyframes activeComposerRail {{" in source
    assert '.composer-active-work[data-transport="stale"]' in source
    assert "function renderComposerActiveWork(snapshot = state.snapshot) {{" in source
    assert "function composerSyncSignal(snapshot = state.snapshot) {{" in source
    assert "Normal submit queues behind this run." in source
    assert "Queue sends behind it" in source
    assert "sync ${{formatElapsedCompact(ageSeconds)}} old" in source
    assert "`Transport: ${{sync.label}}.`" in source
    assert "${{TAB_TITLE_LABEL}} · running" in source
    assert "● ${{TAB_TITLE_LABEL}} running" not in source
    assert 'motion: "orbit"' in source
    assert 'motion: "breathe"' in source
    assert "function tabFaviconMotionInterval(descriptor) {{" in source
    assert "prefers-reduced-motion: reduce" in source
    assert "state.tabFaviconFrame = (state.tabFaviconFrame + 1) % 24;" in source
    assert "const fontSize = mark.length > 1 ? 18 : 28;" in source
    assert 'width="30" height="30" rx="10"' in source
    assert 'stroke-width="5.6"' in source
    assert 'font-weight="800"' in source
    assert (
        "Queue next prompt behind the current reply. Active work continues above the input."
        in source
    )
    assert "setAskButtonState(label, icon, displayLabel = label)" in source
    assert (
        "function promptConflictInSnapshot(snapshot, prompt, attachments = []) {{"
        in source
    )
    assert "const existingConflict = promptConflictInSnapshot(" in source
    assert (
        "duplicate send ignored. Active work is still visible above the input."
        in source
    )


def test_prompt_submission_recovery_does_not_immediately_rehydrate_composer() -> None:
    source = _agent_console_web_source()

    assert "PROMPT_SUBMISSION_RESTORE_GRACE_MS = 1000 * 90" in source
    assert "const submission = loadPromptSubmission();" in source
    assert "promptReceiptMatches(draft, submission.value)" in source
    assert "clearPromptDraft();" in source
    assert "Date.now() - submittedAt < PROMPT_SUBMISSION_RESTORE_GRACE_MS" in source
    assert "Restored a prompt that left the composer but is not visible" in source


def test_template_keeps_upload_tray_items_visible_until_resolved() -> None:
    source = _agent_console_web_source()

    assert "uploadTrayItems: []" in source
    assert "uploadTraySerial: 0" in source
    assert "function createUploadTrayItem(file, source) {{" in source
    assert 'upload_state: "queued"' in source
    assert "function updateUploadTrayItem(uploadId, patch = {{}}) {{" in source
    assert "function dismissUploadTrayItem(uploadId, options = {{}}) {{" in source
    assert "async function retryUploadTrayItem(uploadId) {{" in source
    assert "function hasActiveUploadTrayItems() {{" in source
    assert "function uploadTraySignature(items = state.uploadTrayItems) {{" in source
    assert "function uploadTraySummary(entry) {{" in source
    assert (
        'chip.classList.add("attachment-upload-item", `upload-state-${{uploadState}}`);'
        in source
    )
    assert 'status.className = "attachment-upload-status";' in source
    assert 'retryButton.textContent = "Retry";' in source
    assert "removeButton.disabled = uploadTrayStateIsActive(uploadState);" in source
    assert "[...uploadItems, ...attachments]" in source
    assert "hasActiveUploadTrayItems();" in source
    assert (
        "Files are still attaching. Wait for upload status to settle before sending."
        in source
    )
    assert 'upload_state: "failed"' in source
    assert 'upload_state: "rejected"' in source
    assert ".attachment-chip.attachment-upload-item {{" in source
    assert ".attachment-chip.upload-state-uploading," in source
    assert ".attachment-retry {{" in source


def test_json_response_ignores_client_disconnects() -> None:
    module = _load_agent_console_web()
    handler = object.__new__(module.Handler)
    handler.path = "/api/status"
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.maybe_send_auth_cookie = lambda params: None
    handler.end_headers = lambda: None

    class BrokenWriter:
        def write(self, _value):
            raise BrokenPipeError()

    handler.wfile = BrokenWriter()

    module.Handler.json_response(handler, {"ok": True})


def test_restart_readiness_snapshot_is_lightweight(monkeypatch) -> None:
    module = _load_agent_console_web()
    monkeypatch.setattr(module, "recover_stale_prompt_state", lambda: None)
    monkeypatch.setattr(
        module,
        "load_status_meta",
        lambda: {
            "pending": True,
            "state": "running",
            "status_message": "Working.",
            "queued_prompts": [{"id": "queued-1", "prompt": "queued work"}],
            "active_child_pid": 123,
            "active_child_started_at": 456,
            "last_started_at": 789,
        },
    )
    monkeypatch.setattr(module, "active_codex_process_alive", lambda: True)
    monkeypatch.setattr(module, "prompt_runtime_alive", lambda: True)
    monkeypatch.setattr(module, "now_ts", lambda: 1000)
    monkeypatch.setattr(
        module,
        "load_history",
        lambda limit=module.MAX_HISTORY_ITEMS: [{"prompt": "prior work"}],
    )

    def fake_read_text(path, default=""):
        if path == module.THREAD_ID_PATH:
            return "thread-abcdef123456"
        if path == module.THREAD_SCOPE_PATH:
            return "bedrock:gpt-5.5"
        if path == module.LAST_PROMPT_PATH:
            return "last prompt"
        if path == module.LAST_RESPONSE_PATH:
            return "last response"
        if path == module.LAST_ERROR_PATH:
            return ""
        return default

    monkeypatch.setattr(module, "read_text", fake_read_text)
    monkeypatch.setattr(
        module,
        "web_process_update_snapshot",
        lambda: {
            "web_restart_required": True,
            "web_restart_reason": "changed",
        },
    )
    monkeypatch.setattr(
        module,
        "current_bbs_summary",
        lambda: (_ for _ in ()).throw(AssertionError("BBS should not be sampled")),
    )

    snapshot = module.restart_readiness_snapshot()

    context_handoff = snapshot.pop("context_handoff")
    assert context_handoff["schema"] == "norman.tui.restart-handoff.v1"
    assert context_handoff["scope"] == "web"
    assert context_handoff["thread_id"] == "thread-abcdef123456"
    assert context_handoff["thread_scope"] == "bedrock:gpt-5.5"
    assert context_handoff["can_resume_thread"] is True
    assert context_handoff["context_preserved"] is True
    assert context_handoff["history_count"] == 1
    assert context_handoff["queue_depth"] == 1
    assert "thread thread-a" in context_handoff["summary"]
    assert snapshot == {
        "schema": "norman.tui.restart-readiness.v1",
        "pending": True,
        "busy": True,
        "state": "running",
        "status": "Working.",
        "status_message": "Working.",
        "queue_depth": 1,
        "active_child_pid": 123,
        "active_child_started_at": 456,
        "model_process_alive": True,
        "web_worker_alive": True,
        "last_started_at": 789,
        "last_finished_at": 0,
        "updated_at": 1000,
        "web_restart_required": True,
        "web_restart_reason": "changed",
    }


def test_template_exposes_restart_readiness_endpoint() -> None:
    source = _agent_console_web_source()

    assert "def restart_readiness_snapshot()" in source
    assert "def schedule_web_only_restart(" in source
    assert 'if parsed.path == "/api/restart-readiness":' in source
    assert "self.json_response(restart_readiness_snapshot())" in source
    assert 'if parsed.path in {"/web-restart", "/api/web-restart"}:' in source
    assert "schedule_web_only_restart(actor_ip=self.request_client_ip())" in source
    assert "context_handoff" in source
    assert "restart_handoff" in source


def test_restart_session_records_context_handoff(monkeypatch) -> None:
    module = _load_agent_console_web()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        module,
        "write_restart_handoff",
        lambda scope, reason="": calls.append(("handoff", (scope, reason)))
        or {
            "summary": "Context handoff ready: thread abcdef12.",
        },
    )
    monkeypatch.setattr(
        module,
        "run",
        lambda command, **_kwargs: calls.append(("run", command)),
    )
    monkeypatch.setattr(
        module,
        "ensure_session",
        lambda: calls.append(("ensure", True)) or True,
    )
    monkeypatch.setattr(
        module,
        "record_action",
        lambda action, detail: calls.append(("record", (action, detail))),
    )

    module.restart_session()

    assert calls[0][0] == "handoff"
    assert calls[0][1][0] == "tmux"
    assert any(item[0] == "ensure" for item in calls)
    record = [item for item in calls if item[0] == "record"][0]
    assert record[1][0] == "tmux-restart"
    assert "Context handoff ready" in record[1][1]


def test_schedule_web_only_restart_uses_web_service_not_codex_session(
    monkeypatch,
) -> None:
    module = _load_agent_console_web()
    calls: list[tuple[str, object]] = []
    module.WEB_RESTART_SCHEDULED_AT = 0
    monkeypatch.setattr(module, "WEB_SERVICE", "norman-codex-web.service")
    monkeypatch.setattr(module, "CODEX_SERVICE", "norman-codex.service")
    monkeypatch.setattr(
        module,
        "restart_readiness_snapshot",
        lambda: {
            "web_restart_required": True,
            "busy": False,
        },
    )
    monkeypatch.setattr(
        module,
        "write_restart_handoff",
        lambda scope, reason="": calls.append(("handoff", (scope, reason)))
        or {
            "id": "handoff-1",
            "summary": "Context handoff ready.",
        },
    )
    monkeypatch.setattr(
        module,
        "update_status_meta",
        lambda **kwargs: calls.append(("status", kwargs)) or kwargs,
    )
    monkeypatch.setattr(
        module,
        "append_audit_event",
        lambda **kwargs: calls.append(("audit", kwargs)),
    )
    monkeypatch.setattr(module, "read_text", lambda _path, default="": default)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)

    class FakeThread:
        def __init__(self, target, name="", daemon=False):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            calls.append(("thread", (self.name, self.daemon)))
            self.target()

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(module.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        module,
        "run",
        lambda command, **_kwargs: calls.append(("run", command)) or FakeProc(),
    )

    result = module.schedule_web_only_restart(actor_ip="127.0.0.1")

    assert result["ok"] is True
    assert result["service"] == "norman-codex-web.service"
    assert ("run", ["systemctl", "restart", "norman-codex-web.service"]) in calls
    assert ("run", ["systemctl", "restart", "norman-codex.service"]) not in calls
    assert calls[0][0] == "handoff"
    assert calls[0][1][0] == "web"


def test_schedule_web_only_restart_refuses_codex_service_alias(monkeypatch) -> None:
    module = _load_agent_console_web()
    module.WEB_RESTART_SCHEDULED_AT = 0
    monkeypatch.setattr(module, "WEB_SERVICE", "norman-codex.service")
    monkeypatch.setattr(module, "CODEX_SERVICE", "norman-codex.service")
    monkeypatch.setattr(
        module,
        "restart_readiness_snapshot",
        lambda: {
            "web_restart_required": True,
            "busy": False,
        },
    )

    result = module.schedule_web_only_restart()

    assert result["ok"] is False
    assert "web-only restart is not available" in result["error"]


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
    assert 'monitor.setAttribute("aria-label", intervention ?' in source
    assert 'data-monitor-minimize="${{escapeHtml(interventionKey)}}"' in source


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
    assert "INLINE_SERVICE_ENTITY_DEFS" in source
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
    assert '.entity-cartouche[data-kind="service"],' in source
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
    assert (
        "renderEntityCartouche(entry.entity, visible, {{ aliasFor: entry.aliasFor }})"
        in source
    )
    assert '"toy-box.home.arpa"' in source
    assert '"toy-box.tail94915.ts.net"' in source
    assert '"private.home.lollie.org"' in source
    assert '"192.168.2.241"' in source
    assert '"Norman Prime"' in source
    assert '"Scout / Ranger"' in source
    assert '"Phone Ops"' in source
    assert '"CloudAgent"' in source
    assert '"Dohio"' in source
    assert '"Uplink"' in source
    assert '"Keystone"' in source
    assert '"USCache"' in source
    assert '"USBHome"' in source
    assert '"Panelbot"' in source
    assert '"Norman Ops"' in source
    assert '"Subprime"' in source
    assert '"Diamond ROC"' in source
    assert '"NetOps"' in source
    assert '"netops"' in source
    assert '"networking.home.arpa"' in source
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


def test_template_promotes_final_status_words_into_outcome_sigils() -> None:
    source = _agent_console_web_source()

    assert "OUTCOME_SIGILS" in source
    assert "INITIAL_OUTCOME_SIGIL_RE" in source
    assert "function renderOutcomeSigil(label) {{" in source
    assert "function highlightOutcomeSigils(text) {{" in source
    assert "text = highlightOutcomeSigils(text);" in source
    assert 'class="outcome-sigil"' in source
    assert '.outcome-sigil[data-outcome="done"],' in source
    assert '.outcome-sigil[data-outcome="blocked"],' in source
    assert '.outcome-sigil[data-outcome="checkpoint"],' in source
    assert 'data-decorator="${{escapeHtml(sigil.decorator)}}"' in source


def test_template_keeps_header_agent_cartouche_stable() -> None:
    source = _agent_console_web_source()

    assert "agent_brand_cartouche_html = _render_name_cartouche(" in source
    assert "min-height: 30px;" in source
    assert '<h1 id="agent-title" class="brand-title"' in source
    assert "const AGENT_BRAND_CARTOUCHE_HTML =" in source
    assert 'agentTitle: document.getElementById("agent-title"),' in source
    assert "function ensureAgentBrandCartouche() {{" in source
    assert "el.agentTitle.innerHTML = expectedAgentBrandCartoucheHtml();" in source
    assert "new MutationObserver(() => ensureAgentBrandCartouche())" in source
    assert "grid-template-columns: auto minmax(0, auto);" in source
    assert ".brand-title .entity-cartouche::after {{" in source
    assert "content: none;" in source
    assert ".brand-title .entity-cartouche {{" in source
    assert "body.chat-scrolled .brand-title .entity-cartouche {{" in source


def test_initial_inline_markup_marks_tui_alias_host_and_people_cartouches() -> None:
    module = _load_agent_console_web()

    rendered = module._render_initial_inline_markup(
        "Norman Prime, Subprime, Switchboard, Scout / Ranger, Phone Ops, "
        "Norman Ops, Control Plane, Diamond ROC, Glimpser / Eyebat, "
        "CloudAgent, Dohio, Uplink, NetOps, networking, "
        "networking.home.arpa, toy-box.home.arpa, me, Example",
        token="",
        profile="",
        route="",
    )

    assert rendered.count('data-kind="tui"') >= 8
    assert rendered.count('data-kind="service"') >= 4
    assert 'data-kind="host"' in rendered
    assert 'data-kind="person"' in rendered
    assert 'data-group="norman"' in rendered
    assert 'data-group="operator" data-alias="true"' in rendered
    assert 'data-group="family"' in rendered
    assert 'data-alias-for="Switchboard"' in rendered
    assert 'data-alias-for="Eyebat"' in rendered
    assert ">Norman Prime<" in rendered
    assert ">Subprime<" in rendered
    assert ">Norman Ops<" in rendered
    assert ">Switchboard<" in rendered
    assert ">CloudAgent<" in rendered
    assert ">Dohio<" in rendered
    assert ">Uplink<" in rendered
    assert ">NetOps<" in rendered
    assert 'data-alias-for="Networking Host"' in rendered
    assert ">networking<" in rendered
    assert ">networking.home.arpa<" in rendered
    assert ">Scout / Ranger<" in rendered
    assert ">toy-box.home.arpa<" in rendered


def test_recovered_queue_pruning_preserves_normal_queued_work() -> None:
    module = _load_agent_console_web()
    now = 2000
    meta = {
        **module.default_status_meta(),
        "pending": False,
        "state": "recovered",
        "status_message": "Recovered queued work after restart.",
        "queued_prompts": [
            {
                "prompt": "abandoned recovered prompt",
                "queued_at": now - module.RECOVERED_QUEUE_TTL_SECONDS - 1,
                "source": "recovered",
                "recovered": True,
            },
            {
                "prompt": "normal operator follow-up",
                "queued_at": now - 30,
                "source": "operator",
            },
        ],
        "stale_queue": True,
        "recovered_after_restart": True,
    }

    pruned, removed = module.prune_stale_recovered_queue_items(
        meta, history=[], now=now
    )

    assert removed == 1
    assert [item["prompt"] for item in pruned["queued_prompts"]] == [
        "normal operator follow-up"
    ]
    assert pruned["state"] == "ok"
    assert pruned["status_message"] == "Queued work is waiting."
    assert pruned["stale_queue"] is False
    assert pruned["recovered_after_restart"] is False


def test_recent_recovered_queue_stays_parked_for_review() -> None:
    module = _load_agent_console_web()
    now = 2000
    meta = {
        **module.default_status_meta(),
        "pending": False,
        "state": "recovered",
        "queued_prompts": [
            {
                "prompt": "recent recovered prompt",
                "queued_at": now - 30,
                "source": "recovered",
                "recovered": True,
            },
        ],
    }

    pruned, removed = module.prune_stale_recovered_queue_items(
        meta, history=[], now=now
    )

    assert removed == 0
    assert pruned["state"] == "recovered"
    assert pruned["queued_prompts"][0]["prompt"] == "recent recovered prompt"
    assert pruned["stale_queue"] is True
    assert pruned["recovered_after_restart"] is True


def test_start_next_queued_prompt_does_not_auto_run_recovered_only_queue(
    monkeypatch,
) -> None:
    module = _load_agent_console_web()
    saved: list[dict[str, object]] = []
    meta = {
        **module.default_status_meta(),
        "pending": False,
        "state": "recovered",
        "queued_prompts": [
            {
                "prompt": "parked recovered prompt",
                "queued_at": 1990,
                "source": "recovered",
                "recovered": True,
            },
        ],
    }

    monkeypatch.setattr(module, "now_ts", lambda: 2000)
    monkeypatch.setattr(module, "load_history", lambda limit=0: [])
    monkeypatch.setattr(module, "load_status_meta", lambda: dict(meta))
    monkeypatch.setattr(
        module,
        "save_status_meta",
        lambda payload: saved.append(dict(payload)) or payload,
    )
    monkeypatch.setattr(module, "write_text", lambda path, value: None)

    assert module.start_next_queued_prompt() is None
    assert saved
    assert saved[-1]["state"] == "recovered"
    assert saved[-1]["stale_queue"] is True
    assert saved[-1]["queued_prompts"][0]["prompt"] == "parked recovered prompt"


def test_start_next_queued_prompt_skips_recovered_and_runs_normal_queue(
    monkeypatch,
) -> None:
    module = _load_agent_console_web()
    saved: list[dict[str, object]] = []
    writes: list[tuple[str, str]] = []
    meta = {
        **module.default_status_meta(),
        "pending": False,
        "state": "recovered",
        "queued_prompts": [
            {
                "prompt": "parked recovered prompt",
                "queued_at": 1990,
                "source": "recovered",
                "recovered": True,
            },
            {
                "prompt": "normal operator follow-up",
                "queued_at": 1991,
                "source": "operator",
            },
        ],
    }

    monkeypatch.setattr(module, "now_ts", lambda: 2000)
    monkeypatch.setattr(module, "load_history", lambda limit=0: [])
    monkeypatch.setattr(module, "load_status_meta", lambda: dict(meta))
    monkeypatch.setattr(
        module,
        "save_status_meta",
        lambda payload: saved.append(dict(payload)) or payload,
    )
    monkeypatch.setattr(
        module,
        "write_text",
        lambda path, value: writes.append((path.name, str(value))),
    )

    result = module.start_next_queued_prompt()

    assert result is not None
    assert result[0] == "normal operator follow-up"
    assert ("last_prompt.txt", "normal operator follow-up") in writes
    assert saved[-1]["pending"] is True
    assert [item["prompt"] for item in saved[-1]["queued_prompts"]] == [
        "parked recovered prompt"
    ]
    assert saved[-1]["stale_queue"] is False


def test_active_codex_process_alive_uses_runtime_pid_guard(monkeypatch) -> None:
    module = _load_agent_console_web()
    checked: list[int] = []

    monkeypatch.setattr(module, "ACTIVE_CODEX_PROC", None)
    monkeypatch.setattr(module, "load_status_meta", lambda: {"active_child_pid": 123})
    monkeypatch.setattr(
        module,
        "codex_runtime_pid_alive",
        lambda pid: checked.append(pid) or False,
    )

    assert module.active_codex_process_alive() is False
    assert checked == [123]


def test_template_reports_child_process_as_running_not_waiting() -> None:
    source = _agent_console_web_source()

    assert 'status_message="Model process running."' in source
    assert 'status_message="Waiting for model process."' not in source


def test_template_exposes_context_save_affordance() -> None:
    source = _agent_console_web_source()

    assert 'id="context-save-button"' in source
    assert 'id="context-save-menu-button"' in source
    assert "function buildContextSavePrompt(context) {" in source
    assert "function handleContextSaveAction(button) {" in source
    assert "concise indexed handoff" in source
    assert "old context is now stale or safe to ignore" in source
    assert "Do not paste raw logs or long history" in source
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
    assert "const PROMPT_SUBMISSION_STORAGE_KEY =" in source
    assert "const PROMPT_SUBMISSION_MAX_AGE_MS =" in source
    assert "function safeStorageRemove(key) {{" in source
    assert "function loadPromptDraft() {{" in source
    assert "function persistPromptDraft(value = el.promptInput.value) {{" in source
    assert "function restorePromptDraft() {{" in source
    assert "function clearPromptDraft() {{" in source
    assert "function persistPromptSubmission(value, options = {{}}) {{" in source
    assert "function reconcilePromptSubmission(snapshot = state.snapshot) {{" in source
    assert "snapshotIncludesPromptSubmission(snapshot, value)" in source
    assert 'persistPromptSubmission(message, {{ state: "sending" }});' in source
    assert (
        'persistPromptSubmission(message, {{ state: "accepted", acceptedAt: Date.now() }});'
        in source
    )
    assert "clearPromptSubmission();" in source
    assert "persistPromptDraft(el.promptInput.value);" in source
    assert "clearPromptDraft();" in source
    assert 'window.addEventListener("beforeunload", () => {{' in source
    assert 'if (document.visibilityState === "hidden") {{' in source
    assert "reconcilePromptSubmission(snapshot);" in source
    assert "restorePromptDraft();" in source


def test_console_subprocess_helpers_detach_stdin() -> None:
    source = _agent_console_web_source()
    sync_source = _sync_agent_console_template_source()

    assert 'kwargs["stdin"] = subprocess.DEVNULL' in source
    assert "stdin=subprocess.DEVNULL,\n            stderr=subprocess.DEVNULL" in source
    assert (
        "stdin=subprocess.DEVNULL,\n                    capture_output=True" in source
    )
    assert "subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)" in sync_source
    assert "stdin=subprocess.DEVNULL,\n        capture_output=True" in sync_source


def test_template_exposes_status_capsule_strip() -> None:
    source = _agent_console_web_source()

    assert 'id="kpi-strip"' in source
    assert 'id="system-runtime-metrics"' in source
    assert "function normalizeKpiTone(value) {" in source
    assert "function normalizeResourceKpiMeters(snapshot) {" in source
    assert "function usageCapsuleState(snapshot) {" in source
    assert "function timeTargetCapsuleState(snapshot) {" in source
    assert "function timeProgressSparkline(percent) {" in source
    assert 'id: "time-target"' in source
    assert 'label: "Time"' in source
    assert "function turnQualityDescriptor(item) {" in source
    assert "function lastTurnQualityCapsule(snapshot) {" in source
    assert "function driftSeverityLevel(kind, value, power) {" in source
    assert "function driftAlignmentSparkline(drift) {" in source
    assert "function driftCapsuleState(snapshot) {" in source
    assert "snapshot.drift_assessment" in source
    assert 'id: "drift"' in source
    assert 'label: "Align"' in source
    assert "const sparkline = driftAlignmentSparkline(drift);" in source
    assert "Recommended action" in source
    assert "Low yield" in source
    assert "Short reply after a heavy turn" in source
    assert "message-quality-chip" in source
    assert "function buildStatusCapsules(snapshot) {" in source
    assert "function renderStatusCapsules(snapshot) {" in source
    assert "function renderSystemRuntimeMetrics(snapshot) {" in source
    assert "NORMAN_CODEX_RESOURCE_METER_PATH" in source
    assert "def load_resource_meter_file() -> dict[str, Any]:" in source
    assert "snapshot.resource_meter || {{}}" in source
    assert 'if (clean === "danger" || clean === "alert") return "alert";' in source
    assert "return [...adapterCapsules, ...fallbackCapsules].slice(0, 7);" in source
    assert "function bbsStatusCapsule(snapshot) {" in source
    assert "handoff.needs_ack" in source
    assert 'button.dataset.kpiAction = String(item.action || "system");' in source
    assert 'const action = String(capsule.dataset.kpiAction || "system");' in source
    assert 'if (action === "notices") {' in source


def test_web_process_update_snapshot_flags_staged_restart(tmp_path: Path) -> None:
    module = _load_agent_console_web()
    script_path = tmp_path / "agent_console_web.py"
    script_path.write_text("print('updated')\n", encoding="utf-8")
    os.utime(script_path, (200, 200))

    module.WEB_PROCESS_STARTED_AT = 100
    module.WEB_SCRIPT_PATH = script_path
    module.WEB_UPDATE_GRACE_SECONDS = 0

    snapshot = module.web_process_update_snapshot()

    assert snapshot["web_process_started_at"] == 100
    assert snapshot["web_script_updated_at"] == 200
    assert snapshot["web_restart_required"] is True
    assert "changed after this process started" in snapshot["web_restart_reason"]


def test_web_process_seen_records_refresh_event(monkeypatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()
    module.WEB_PROCESS_EVENT_RECORDED = False
    module.WEB_PROCESS_STARTED_AT = 222
    monkeypatch.setattr(module, "now_ts", lambda: 333)
    monkeypatch.setattr(module, "read_text", lambda _path, default="": "thread-refresh")

    updated_meta, event = module.record_web_process_seen(
        {
            "web_process_seen_ui_version": "2026.06.07.1",
            "web_process_seen_started_at": 111,
        }
    )

    assert event["changed"] is True
    assert event["event_at"] == 333
    assert event["previous_ui_version"] == "2026.06.07.1"
    assert event["previous_process_started_at"] == 111
    assert updated_meta["web_process_seen_ui_version"] == module.UI_VERSION
    with sqlite3.connect(state_db) as conn:
        row = conn.execute(
            "SELECT event_type, summary, thread_id FROM audit_events"
        ).fetchone()
    assert row == (
        "web.process_refreshed",
        f"UI wrapper refreshed to {module.UI_VERSION}.",
        "thread-refresh",
    )


def test_template_exposes_web_restart_staged_capsule() -> None:
    source = _agent_console_web_source()

    assert "web_restart_required" in source
    assert 'id: "web-update"' in source
    assert 'value: "Restart staged"' in source
    assert 'action: "web-restart"' in source
    assert 'actionTitle: "Apply the staged web-only TUI restart.' in source
    assert "dataset.activityAction = stripAction" in source
    assert "[data-activity-action]" in source
    assert (
        'performNoticeAction(String(activityAction.dataset.activityAction || "peek"))'
        in source
    )
    assert 'postForm("/api/web-restart", {{}})' in source
    assert "function requestWebRestart() {{" in source
    assert "Web-only restart scheduled for ${{service}}. Reloading shortly…" in source
    assert "def defer_web_only_restart_until_idle(" in source
    assert "WEB_RESTART_DEFERRED_MAX_WAIT_SECONDS" in source
    assert "Web-only restart queued until idle." in source
    assert "web.restart.deferred" in source
    assert '"web_restart_deferred": True' in source
    assert "Apply staged web restart" in source
    assert "Console script changed after this web process started" in source
    assert "Context resumable" in source
    assert "Context checked" in source
    assert "restart staged/resumable" in source


def test_template_surfaces_ui_refresh_notices() -> None:
    source = _agent_console_web_source()

    assert "function syncUiVersionNotice(snapshot = state.snapshot) {{" in source
    assert "norman:tui-ui-version" in source
    assert "Updated from ${{previousVersion}} to ${{currentVersion}}" in source
    assert "Thread, queue, and SQLite-backed state remain on disk." in source
    assert "Wrapper process refreshed" in source
    assert "syncUiVersionNotice(snapshot);" in source


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
    commands = []

    class _FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            self.cmd = cmd
            commands.append(cmd)
            assert text is True
            assert stdin == module.subprocess.DEVNULL
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
    assert "Time target: Normal" in commands[0][-1]
    assert "Local guardrail: this TUI may terminate the turn after" in commands[0][-1]
    assert "Close-up warnings:" in commands[0][-1]


def test_execute_codex_prompt_records_deadline_warning(monkeypatch) -> None:
    module = _load_agent_console_web()
    state_dir = Path(tempfile.mkdtemp()) / "state"
    module.STATE_DIR = state_dir
    module.THREAD_ID_PATH = state_dir / "thread_id.txt"
    module.THREAD_SCOPE_PATH = state_dir / "thread_scope.txt"
    module.STATUS_PATH = state_dir / "status.json"
    module.AUDIT_PATH = state_dir / "audit.jsonl"

    class _FakePopen:
        pid = 34567
        returncode = 0

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            self.cmd = cmd
            assert text is True
            assert stdin == module.subprocess.DEVNULL
            assert stdout == module.subprocess.PIPE
            assert stderr == module.subprocess.PIPE
            assert start_new_session is True
            (state_dir / "last_message.txt").parent.mkdir(parents=True, exist_ok=True)
            (state_dir / "last_message.txt").write_text("ok", encoding="utf-8")

    def fake_communicate_with_prompt_timeout(
        popen,
        timeout_seconds=None,
        stdout_line_callback=None,
        deadline_warning_callback=None,
        deadline_warning_checkpoints=None,
    ):
        assert timeout_seconds == module.normalize_job_timeout_seconds(900, "15m")
        assert deadline_warning_callback is not None
        assert deadline_warning_checkpoints
        target_warning = next(
            item
            for item in deadline_warning_checkpoints
            if "target" in str(item.get("kind") or "")
        )
        deadline_warning_callback(target_warning)
        return (
            '{"type":"thread.started","thread_id":"thread-warning"}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}\n',
            "",
            False,
        )

    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(
        module,
        "communicate_with_prompt_timeout",
        fake_communicate_with_prompt_timeout,
    )

    response, error_text, thread_id, usage = module._execute_codex_prompt(
        "long run", "slow", 3, [], 900, service_tier="flex", job_budget="15m"
    )

    meta = module.load_status_meta()
    audits = module.load_audit_events(limit=10)

    assert response == "ok"
    assert error_text == ""
    assert thread_id == "thread-warning"
    assert usage["total_tokens"] == 15
    assert meta["deadline_warning_active"] is True
    assert meta["deadline_warning_count"] == 1
    assert "Time target reached" in meta["status_message"]
    assert meta["deadline_warning_target_seconds"] == 900
    assert meta["deadline_warning_guardrail_seconds"] == 1500
    assert audits[-1]["event_type"] == "chat.deadline-warning"
    assert audits[-1]["payload"]["service_tier"] == "flex"


def test_execute_codex_prompt_interrupts_at_deadline_checkpoint(monkeypatch) -> None:
    module = _load_agent_console_web()
    state_dir = Path(tempfile.mkdtemp()) / "state"
    module.STATE_DIR = state_dir
    module.THREAD_ID_PATH = state_dir / "thread_id.txt"
    module.THREAD_SCOPE_PATH = state_dir / "thread_scope.txt"
    module.STATUS_PATH = state_dir / "status.json"
    module.AUDIT_PATH = state_dir / "audit.jsonl"
    killed: list[tuple[int, int]] = []

    class _FakePopen:
        pid = 45678
        returncode = -15

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            self.cmd = cmd
            assert text is True
            assert stdin == module.subprocess.DEVNULL
            assert stdout == module.subprocess.PIPE
            assert stderr == module.subprocess.PIPE
            assert start_new_session is True

    def fake_communicate_with_prompt_timeout(
        popen,
        timeout_seconds=None,
        stdout_line_callback=None,
        deadline_warning_callback=None,
        deadline_warning_checkpoints=None,
    ):
        assert stdout_line_callback is not None
        assert deadline_warning_callback is not None
        target_warning = next(
            item
            for item in deadline_warning_checkpoints
            if "target" in str(item.get("kind") or "")
        )
        deadline_warning_callback(target_warning)
        stdout_line_callback('{"type":"tool.completed","tool":"pytest"}\n')
        return (
            '{"type":"thread.started","thread_id":"thread-deadline"}\n'
            '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":7}}\n',
            "",
            False,
        )

    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        module,
        "terminate_process_group",
        lambda pid, pgid: killed.append((pid, pgid)),
    )
    monkeypatch.setattr(
        module,
        "communicate_with_prompt_timeout",
        fake_communicate_with_prompt_timeout,
    )
    monkeypatch.setattr(module, "DEADLINE_CHECKPOINT_POLICY", "target")

    response, error_text, thread_id, usage = module._execute_codex_prompt(
        "long run", "slow", 3, [], 900, service_tier="flex", job_budget="15m"
    )

    meta = module.load_status_meta()
    audits = module.load_audit_events(limit=10)

    assert response == ""
    assert error_text == module.DEADLINE_CHECKPOINT_INTERRUPTED_WEB_REPLY_MESSAGE
    assert thread_id == "thread-deadline"
    assert usage["total_tokens"] == 19
    assert killed == [(45678, 45678)]
    assert meta["deadline_checkpoint_state"] == "interrupting"
    assert "pytest" in meta["deadline_checkpoint_tool"]
    assert any(event["event_type"] == "chat.deadline-checkpoint" for event in audits)


def test_deadline_checkpoint_auto_continues_past_soft_target() -> None:
    module = _load_agent_console_web()

    assert module.DEADLINE_CHECKPOINT_POLICY == "auto"
    assert not module.deadline_checkpoint_policy_allows(
        {
            "deadline_checkpoint_policy": "auto",
            "deadline_warning_kind": "target",
            "deadline_warning_remaining_seconds": 10 * 60,
        }
    )
    assert module.deadline_checkpoint_policy_allows(
        {
            "deadline_checkpoint_policy": "auto",
            "deadline_warning_kind": "remaining",
            "deadline_warning_remaining_seconds": 5 * 60,
        }
    )
    assert module.deadline_checkpoint_policy_allows(
        {
            "deadline_checkpoint_policy": "target",
            "deadline_warning_kind": "target",
            "deadline_warning_remaining_seconds": 10 * 60,
        }
    )


def test_deadline_checkpoint_continuation_prompt_is_auto_continuation() -> None:
    module = _load_agent_console_web()

    prompt = module.build_deadline_checkpoint_continuation_prompt(
        "finish the deployment audit",
        checkpoint_detail="paused after make test",
        warning_message="Time target reached after 15 minutes.",
        remaining_seconds=600,
    )

    assert module.AUTO_CONTINUE_DEADLINE_MARKER in prompt
    assert module.prompt_is_auto_continuation(prompt) is True
    assert "do not restart broad setup" in prompt
    assert "Approximate hard-guardrail remaining" in prompt


def test_zero_token_provider_retry_prompt_is_auto_continuation() -> None:
    module = _load_agent_console_web()

    prompt = module.build_zero_token_provider_retry_prompt(
        "Run the release checks.",
        (
            "stream disconnected before completion: The server had an error while "
            "processing your request. Sorry about that!"
        ),
        {
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_stream_disconnected",
            "provider_request_ids": ["req-abc"],
            "provider_trace_ids": ["trace-def"],
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        },
    )

    assert module.AUTO_CONTINUE_ZERO_TOKEN_PROVIDER_MARKER in prompt
    assert module.prompt_is_auto_continuation(prompt) is True


def test_zero_token_provider_recovery_response_keeps_resume_bounded() -> None:
    module = _load_agent_console_web()

    response = module.build_zero_token_provider_recovery_response(
        "Clean up the handoffs and assignments.",
        (
            "stream disconnected before completion: The server had an error while "
            "processing your request. Sorry about that!"
        ),
        {
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_stream_disconnected",
            "provider_request_ids": ["req-abc"],
            "provider_trace_ids": ["trace-def"],
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        },
        {
            "live_turn": {
                "tool_started_count": 4,
                "tool_finished_count": 4,
                "file_interaction_count": 2,
                "last_tool": "exec_command",
                "last_file": "/tmp/control-plane-audit.json",
            }
        },
        thread_id="thread-recovery",
        service_tier="default",
        job_budget="normal",
        runtime="codex",
        model="openai.gpt-5.5",
    )

    assert response.startswith("Provider recovery checkpoint")
    assert "Provider error kind: bedrock_stream_disconnected" in response
    assert "Session/thread id: thread-recovery" in response
    assert "Provider request ids: req-abc" in response
    assert "Provider trace ids: trace-def" in response
    assert "tools started=4" in response
    assert "file interactions=2" in response
    assert "last file=control-plane-audit.json" in response
    assert "Do not resend the original prompt unchanged." in response
    assert response.endswith("CHECKPOINT")

    handoff = module.build_zero_token_provider_recovery_handoff_prompt(response)

    assert module.AUTO_CONTINUE_ZERO_TOKEN_PROVIDER_MARKER in handoff
    assert "Provider recovery checkpoint" in handoff
    assert "Do not resend the original prompt unchanged" in handoff
    assert "not repeat completed tool/file work" in handoff
    assert "Make the fallback spend visible" in handoff


def test_visible_provider_error_message_labels_bedrock_failure() -> None:
    module = _load_agent_console_web()

    message = module.visible_provider_error_message(
        (
            "stream disconnected before completion: The server had an error while "
            "processing your request. Sorry about that!"
        ),
        {
            "provider_surface": "aws-bedrock",
            "provider_error_kind": "bedrock_stream_disconnected",
            "total_tokens": 0,
            "zero_token_provider_failure": True,
        },
        service_tier="default",
        model="openai.gpt-5.5",
    )

    assert message.startswith("Bedrock stream failure (bedrock_stream_disconnected)")
    assert "lane=Standard" in message
    assert "model=openai.gpt-5.5" in message
    assert "Original provider error: stream disconnected before completion" in message


def test_visible_provider_error_message_preserves_non_bedrock_failure() -> None:
    module = _load_agent_console_web()

    error = "You've hit your usage limit."

    assert (
        module.visible_provider_error_message(
            error,
            {
                "provider_surface": "openai-direct",
                "provider_error_kind": "codex_provider_error",
                "total_tokens": 0,
            },
            service_tier="flex",
            model="gpt-5.5",
        )
        == error
    )


def test_usage_limit_billing_action_exposes_limits_and_billing_links() -> None:
    module = _load_agent_console_web()

    action = module.usage_limit_billing_action(
        "You've hit your usage limit. Try again later."
    )

    assert action["code"] == "openai_usage_limit"
    assert action["label"] == "Usage limit"
    assert action["billing_url"].endswith("/billing/overview")
    assert action["limits_url"].endswith("/limits")
    assert module.usage_limit_billing_action("ordinary provider failure") == {}


def test_usage_limit_billing_action_classifies_chatgpt_auth_as_codex_cap() -> None:
    module = _load_agent_console_web()

    action = module.usage_limit_billing_action(
        "You've hit your usage limit. To get more access now, send a request "
        "to your admin or try again at 5:28 PM.",
        auth_mode="chatgpt",
        now_epoch=1781530140,
    )

    assert action["code"] == "codex_usage_limit"
    assert action["label"] == "Usage cap"
    assert "API credits may still be available" in action["summary"]
    assert action["reset_hint"] == (
        "June 15, 2026 at 5:28 PM (timezone not provided by provider)"
    )
    assert "Reset hint: June 15, 2026 at 5:28 PM" in action["summary"]
    assert action["billing_url"].endswith("/billing/overview")
    assert action["limits_url"].endswith("/limits")


def test_stale_arg0_cleanup_warning_is_not_provider_error() -> None:
    module = _load_agent_console_web()
    warning = (
        "WARNING: failed to clean up stale arg0 temp dirs: "
        "Permission denied (os error 13)"
    )

    assert module.provider_error_kind(warning, provider_surface="openai-direct") == ""
    assert (
        module.provider_error_kind(
            f"{warning} Task submission failed with status 404 Not Found: Engine not found",
            provider_surface="aws-bedrock",
        )
        == "bedrock_engine_not_found"
    )
    assert (
        module.provider_error_kind(
            "unexpected status 404 Not Found: The model 'openai.gpt-5.5' does not exist",
            provider_surface="aws-bedrock",
        )
        == "bedrock_engine_not_found"
    )


def test_zero_token_provider_retry_service_tier_falls_back_for_bedrock_default() -> (
    None
):
    module = _load_agent_console_web()
    usage = {
        "provider_surface": "aws-bedrock",
        "provider_error_kind": "bedrock_stream_disconnected",
        "total_tokens": 0,
        "zero_token_provider_failure": True,
    }

    assert module.zero_token_provider_retry_service_tier("default", usage) == "flex"
    assert module.zero_token_provider_retry_service_tier("auto", usage) == "flex"
    assert (
        module.zero_token_provider_retry_service_tier(
            "default", {**usage, "provider_surface": "openai-direct"}
        )
        == "default"
    )


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

        def __init__(self, cmd, text, stdin, stdout, stderr, env, start_new_session):
            self.cmd = cmd
            self.returncode = None
            self.calls = 0
            assert text is True
            assert stdin == module.subprocess.DEVNULL
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
            "status?", "slow", 1, [], 4
        )
    finally:
        module.subprocess.Popen = original_popen
        module.terminate_process_group = original_terminate

    assert response == ""
    assert error_text.startswith(
        f"{module.WEB_PROMPT_TIMED_OUT_PREFIX}{module.normalize_job_timeout_seconds(4)} seconds and was terminated."
    )
    assert "Target was" in error_text
    assert "hard guardrail was" in error_text
    assert thread_id == "thread-timeout"
    assert killed == [(23456, 23456)]
    assert usage["total_tokens"] == 0


def test_template_exposes_per_prompt_job_budget_controls() -> None:
    source = _agent_console_web_source()

    assert 'name="job_budget"' in source
    assert 'name="optimization_mode"' in source
    assert 'id="job-budget-range"' in source
    assert 'id="optimization-mode-range"' in source
    assert 'id="prompt-cost-estimate"' in source
    assert "JOB_BUDGET_OPTIONS" in source
    assert "OPTIMIZATION_MODE_OPTIONS" in source
    assert "normalizeJobBudget" in source
    assert "normalizeOptimizationMode" in source
    assert "promptCostProjection" in source
    assert "renderPromptCostEstimate" in source
    assert '"1m"' in source
    assert '"2m"' in source
    assert '"5m"' in source
    assert '"10m"' in source
    assert '"15m"' in source
    assert '"20m"' in source
    assert '"30m"' in source
    assert '"45m"' in source
    assert '"60m"' in source
    assert '"90m"' in source
    assert '"90-min": "90m"' in source
    assert source.count('"1-hour": "60m"') >= 2
    assert source.count('"90-min": "90m"') >= 2
    assert "jobBudgetCostMarker" in source
    assert "jobBudgetNotice" in source
    assert "Cost notice: long runs can be materially expensive" in source
    assert "Reasoning" in source
    assert "Reply" in source
    assert "Spend path" in source
    assert "Work window" in source
    assert "Optimize" in source
    assert "Target the run" in source
    assert "Time first · depth second · billing guarded" in source
    assert "response-rail-primary response-rail-time" in source
    assert "response-rail-emergency response-rail-spend" in source
    assert "Emergency lane" in source
    assert "Only change when blocked" in source
    assert "Primary control: target run time" in source
    assert "Emergency billing override" in source
    assert "Target ${{jobBudgetLabel(preferences.jobBudget)}}" in source
    assert "model calls" in source
    assert "Prefer the Bedrock profile when configured" in source
    assert "Do not idle-poll to fill time" in source
    assert "Time target:" in source
    assert "job_budget: jobBudget" in source
    assert "running_timeout_seconds" in source
    assert "running_optimization_mode" in source


def test_console_source_exposes_low_ui_remote_navigation() -> None:
    source = _agent_console_web_source()

    assert 'id="low-ui-rail"' in source
    assert 'id="low-ui-mode-button"' in source
    assert 'data-low-ui-action="prompt"' in source
    assert 'data-low-ui-action="send"' in source
    assert 'data-low-ui-action="status"' in source
    assert ".low-ui-rail {{\n      position: sticky;" in source
    assert "display: none;\n      align-items: center;" in source
    assert "body.low-ui-mode .low-ui-rail {{\n      display: flex;" in source
    assert "lowUiMode: false" in source
    assert "function handleLowUiRailAction(action)" in source
    assert "function handleLowUiRemoteKey(event)" in source
    assert "body.low-ui-mode .composer-send-label" in source
    assert "--low-ui-rail-top" in source


def test_build_tuned_prompt_includes_timing_target() -> None:
    module = _load_agent_console_web()

    tuned = module.build_tuned_prompt(
        "Do a fast check.", 3, "5m", 5 * 60, "balanced", "auto"
    )

    assert "Time target: 5 min (5 minutes)." in tuned
    assert "Local guardrail: this TUI may terminate the turn after 10 minutes." in tuned
    assert "Honor the selected spend/work controls" in tuned
    assert "Reasoning: Standard (medium)" in tuned
    assert "Reply shape: Balanced" in tuned
    assert "Spend path:" in tuned
    assert "Optimization: Auto" in tuned
    assert "cheapest reliable path" in tuned
    assert "Time contract:" in tuned
    assert "Early finish rule:" in tuned
    assert "Time plan: work backwards from the target" in tuned

    longer = module.build_tuned_prompt("Keep working carefully.", 4, "90m", 90 * 60)
    assert "Time target: 90 min (90 minutes)." in longer
    assert "start wrap-up by 1h 15m elapsed" in longer
    assert "target close-up is 1h 30m" in longer
    assert "Stop opening new branches by" in tuned
    assert "At the stop-new-work mark, narrow scope" in tuned
    assert "At the wrap-up mark" in tuned
    assert "return the fastest useful result" in tuned
    assert "if the task looks likely to exceed the target" in tuned
    assert "Close-up warnings:" in tuned
    assert "Execution discipline: do not stop after an intent sentence" in tuned
    assert "Final-answer contract: end with DONE, BLOCKED, or CHECKPOINT" in tuned
    assert "DONE must include concrete evidence" in tuned
    assert "Do not use the final answer for progress text" in tuned
    assert "`/usr/local/bin/apply_patch`" in tuned
    assert "Context budget: treat long history" in tuned
    assert "fresh fork would preserve quality and lower cost" in tuned

    raw = module.build_tuned_prompt(
        "Compare routes.", 3, "5m", 5 * 60, "balanced", "auto", "raw"
    )
    assert "Optimization: Raw" in raw
    assert "Raw benchmark mode" in raw


def test_codex_stdin_status_line_is_transient_noise() -> None:
    module = _load_agent_console_web()

    assert (
        module.strip_codex_empty_last_message_warning(
            "Reading additional input from stdin...\nreal error"
        )
        == "real error"
    )


def test_build_tuned_prompt_warns_and_continues_for_long_budget() -> None:
    module = _load_agent_console_web()

    tuned = module.build_tuned_prompt("Audit the rollout.", 5, "deep", 2 * 60 * 60)

    assert "Time target: Deep (2 hours)." in tuned
    assert "Long-run mode: do not stop at the first plausible answer" in tuned
    assert "Cost notice: long runs can be materially expensive" in tuned
    assert "before any final destructive" in tuned


def test_time_target_plan_tracks_work_narrow_wrap_and_over_target() -> None:
    module = _load_agent_console_web()

    early = module.time_target_plan("15m", 900, started_at=1000, now=1100, pending=True)
    narrow = module.time_target_plan(
        "15m", 900, started_at=1000, now=1700, pending=True
    )
    wrap = module.time_target_plan("15m", 900, started_at=1000, now=1850, pending=True)
    over = module.time_target_plan("15m", 900, started_at=1000, now=1930, pending=True)

    assert early["phase"] == "work"
    assert early["stop_new_work_after_seconds"] == 660
    assert early["wrap_up_after_seconds"] == 780
    assert early["guardrail_seconds"] == 1500
    assert narrow["phase"] == "narrow"
    assert "Stop opening new branches" in narrow["next_action"]
    assert wrap["phase"] == "wrap_up"
    assert "write the result" in wrap["next_action"]
    assert over["phase"] == "over_target"
    assert "target passed" in over["meta"]


def test_runtime_time_target_snapshot_surfaces_running_phase() -> None:
    module = _load_agent_console_web()

    plan = module.runtime_time_target_snapshot(
        {
            "running_job_budget": "15m",
            "running_timeout_seconds": 900,
            "last_started_at": 1000,
        },
        pending=True,
        snapshot_at=1850,
    )

    assert plan["hidden"] is False
    assert plan["phase"] == "wrap_up"
    assert plan["pending"] is True
    assert plan["value"] == "50s target"
    assert "guardrail" in plan["meta"]


def test_drift_assessment_flags_high_power_work_actions(monkeypatch) -> None:
    monkeypatch.setenv("NORMAN_CODEX_AGENT_NAME", "Control Plane")
    monkeypatch.setenv("NORMAN_CODEX_AGENT_GROUP", "work")
    monkeypatch.setenv("NORMAN_CODEX_WORKDIR", "/home/kristopher/code/control_plane")
    module = _load_agent_console_web()

    assessment = module.assess_tui_drift(
        "Execute the employee offboarding runbook: disable account and revoke access.",
        job_budget="15m",
        timeout_seconds=900,
    )
    prompt_context = module.drift_assessment_prompt_context(assessment)

    assert assessment["tone"] == "alert"
    assert assessment["recommended_action"] == "ask_approval"
    assert assessment["mission_drift"] == "in_lane"
    assert "sword" in assessment["power_drift"]
    assert "Governance drift preflight:" in prompt_context
    assert "explicit approval" in prompt_context


def test_drift_assessment_catches_context_scope_and_cross_lane(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_CODEX_AGENT_NAME", "Control Plane")
    monkeypatch.setenv("NORMAN_CODEX_AGENT_GROUP", "work")
    module = _load_agent_console_web()

    assessment = module.assess_tui_drift(
        "Review all old sessions and system prompts for autocamera and toy-box.",
        attachments=[
            {"token": f"block-{index}", "path": f"/tmp/item-{index}.txt"}
            for index in range(1, 4)
        ],
        job_budget="deep",
        timeout_seconds=2 * 60 * 60,
    )

    assert assessment["tone"] == "alert"
    assert assessment["mission_drift"] == "cross_lane"
    assert assessment["context_drift"] == "possibly_stale"
    assert assessment["scope_drift"] == "over_budget"
    assert assessment["recommended_action"] == "handoff"


def test_build_prompt_with_attachments_includes_drift_preflight(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NORMAN_CODEX_AGENT_NAME", "Control Plane")
    monkeypatch.setenv("NORMAN_CODEX_AGENT_GROUP", "work")
    module = _load_agent_console_web()

    prompt = module.build_prompt_with_attachments(
        "Execute the employee offboarding runbook: disable account and revoke access.",
        3,
        [],
        job_budget="15m",
        timeout_seconds=900,
        runtime="codex",
        model="gpt-5.5",
    )

    assert "Governance drift preflight:" in prompt
    assert "power: sword" in prompt
    assert "Recommended action: ask_approval." in prompt


def test_build_prompt_with_attachments_includes_bbs_handoff_context(
    monkeypatch,
) -> None:
    module = _load_agent_console_web()
    monkeypatch.setattr(
        module,
        "bbs_handoff_prompt_context",
        lambda: "BBS handoff notice for this console:\n- Next owner/coordination action: ACK.",
    )

    prompt = module.build_prompt_with_attachments(
        "Check the queue.",
        2,
        [],
        job_budget="15m",
        timeout_seconds=900,
        runtime="codex",
        model="gpt-5.5",
    )

    assert "BBS handoff notice for this console:" in prompt
    assert "Next owner/coordination action: ACK." in prompt


def test_template_exposes_per_prompt_service_tier_controls() -> None:
    source = _agent_console_web_source()

    assert 'name="service_tier"' in source
    assert 'id="service-tier-range"' in source
    assert "SERVICE_TIER_OPTIONS" in source
    assert "CODEX_STANDARD_PROFILE_V2" in source
    assert "codex_profile_v2_config_args" in source
    assert "apply_codex_provider_environment" in source
    assert "normalizeServiceTier" in source
    assert "service_tier: serviceTier" in source
    assert "running_service_tier" in source
    assert "last_service_tier" in source


def test_job_budget_presets_extend_timeout_without_global_default() -> None:
    module = _load_agent_console_web()

    assert module.normalize_job_budget("1-minute") == "1m"
    assert module.normalize_job_budget("2") == "2m"
    assert module.normalize_job_budget("5-min") == "5m"
    assert module.normalize_job_budget("10") == "10m"
    assert module.normalize_job_budget("15") == "15m"
    assert module.normalize_job_budget("20-minute") == "20m"
    assert module.normalize_job_budget("30-minute") == "30m"
    assert module.normalize_job_budget("45m") == "45m"
    assert module.normalize_job_budget("1-hour") == "60m"
    assert module.normalize_job_budget("90-min") == "90m"
    assert module.normalize_job_budget("high") == "high-impact"
    assert module.normalize_job_budget("overnite") == "overnight"
    assert module.job_budget_timeout_seconds("1m") == 60
    assert module.job_budget_timeout_seconds("2m") == 120
    assert module.job_budget_timeout_seconds("5m") == 300
    assert module.job_budget_timeout_seconds("10m") == 600
    assert module.job_budget_timeout_seconds("15m") == 900
    assert module.job_budget_timeout_seconds("20m") == 1200
    assert module.job_budget_timeout_seconds("30m") == 1800
    assert module.job_budget_timeout_seconds("45m") == 2700
    assert module.job_budget_timeout_seconds("60m") == 3600
    assert module.job_budget_timeout_seconds("90m") == 5400
    assert module.job_budget_guardrail_seconds("15m") == 1500
    assert module.normalize_job_timeout_seconds(900, "15m") == 1500
    assert module.normalize_job_timeout_seconds(901, "15m") == 901
    checkpoints = module.deadline_warning_checkpoints(900, 1500)
    assert [item["remaining_seconds"] for item in checkpoints] == [
        900,
        600,
        300,
        60,
    ]
    assert "target" in checkpoints[1]["kind"]
    guidance = module.timing_target_prompt_guidance("15m", 900)
    assert "Time target: 15 min (15 minutes)." in guidance
    assert "terminate the turn after 25 minutes" in guidance
    assert "15 minutes before guardrail" in guidance
    assert "target mark" in guidance
    timeout_message = module.web_prompt_timed_out_message(
        1500, job_budget="15m", service_tier="flex"
    )
    assert timeout_message.startswith("Web prompt timed out after 1500 seconds")
    assert "Target was 15 minutes" in timeout_message
    assert "hard guardrail was 25 minutes" in timeout_message
    assert "Flex" in timeout_message
    assert (
        module.job_budget_timeout_seconds("normal") == module.WEB_PROMPT_TIMEOUT_SECONDS
    )
    assert (
        module.job_budget_timeout_seconds("deep") >= module.WEB_PROMPT_TIMEOUT_SECONDS
    )
    assert module.job_budget_timeout_seconds(
        "high-impact"
    ) >= module.job_budget_timeout_seconds("deep")
    assert module.job_budget_timeout_seconds(
        "overnight"
    ) >= module.job_budget_timeout_seconds("high-impact")
    assert (
        module.job_budget_timeout_seconds("overnight")
        <= module.WEB_PROMPT_MAX_TIMEOUT_SECONDS
    )
    assert list(module.JOB_BUDGET_PRESETS)[:5] == [
        "1m",
        "2m",
        "5m",
        "10m",
        "15m",
    ]
    assert list(module.JOB_BUDGET_PRESETS)[5:11] == [
        "20m",
        "30m",
        "45m",
        "60m",
        "90m",
        "normal",
    ]


def test_service_tier_presets_normalize_and_emit_codex_config(monkeypatch) -> None:
    for key in (
        "NORMAN_CODEX_STANDARD_PROFILE_V2",
        "HOUSEBOT_CODEX_STANDARD_PROFILE_V2",
        "NORMAN_CODEX_DEFAULT_PROFILE_V2",
        "HOUSEBOT_CODEX_DEFAULT_PROFILE_V2",
        "NORMAN_CODEX_BEDROCK_PROFILE_V2",
        "HOUSEBOT_CODEX_BEDROCK_PROFILE_V2",
    ):
        monkeypatch.delenv(key, raising=False)
    module = _load_agent_console_web()

    assert module.normalize_service_tier("profile") == "auto"
    assert module.normalize_service_tier("standard") == "default"
    assert module.normalize_service_tier("fast") == "priority"
    assert module.normalize_service_tier("flex") == "flex"
    assert module.service_tier_execution_tier("auto") == "flex"
    assert module.service_tier_config_args("auto") == ["-c", 'service_tier="flex"']
    assert module.service_tier_config_args("flex") == ["-c", 'service_tier="flex"']
    assert module.service_tier_config_args("standard") == [
        "-c",
        'service_tier="default"',
    ]
    assert module.codex_profile_v2_config_args("standard") == []


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
        runtime="codex",
        model=module.MODEL,
        usage={"input_tokens": 50, "cached_input_tokens": 10, "output_tokens": 5},
    )
    module.append_usage_entry(
        started_at=now - 90,
        finished_at=now - 60,
        thread_id="recent",
        speed="fast",
        detail=2,
        success=True,
        runtime="codex",
        model=module.MODEL,
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
    assert snapshot["billing"]["schema"] == "norman.tui.billing.v1"
    assert snapshot["billing"]["sparkline"] == [55, 138]
    assert snapshot["billing"]["tag_health"]["state"] in {"ok", "warn"}
    assert (
        snapshot["billing"]["service_tiers"][module.DEFAULT_SERVICE_TIER]["turns"] == 2
    )
    assert snapshot["billing"]["models"][module.MODEL]["total_tokens"] == 193
    assert snapshot["billing"]["last_24h_estimate"]["configured"] is True
    assert snapshot["billing"]["last_24h_estimate"]["credits_configured"] is True
    assert snapshot["billing"]["last_24h_estimate"]["approximate"] is True
    assert (
        snapshot["billing"]["last_24h_estimate"]["ledger_kind"]
        == "chatgpt_codex_credit_estimate"
    )
    assert snapshot["billing"]["last_24h_estimate"]["display_unit"] == "credits"
    assert (
        snapshot["billing"]["last_24h_estimate"]["charge_status"]
        == "not_invoice_reconciled"
    )
    assert snapshot["billing"]["last_24h_estimate"]["credits"] > 0
    expected_rate_model = module.normalize_codex_model_name(
        module.MODEL, fallback=module.MODEL
    )
    expected_rate_model = expected_rate_model.replace("openai.", "").replace(
        "gpt-", "GPT-"
    )
    assert (
        snapshot["billing"]["last_24h_estimate"]["rate_source"]
        == f"OpenAI {expected_rate_model} Standard public rate card"
    )


def test_usage_snapshot_derives_cumulative_codex_deltas() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    entries = [
        {
            "started_at": now - 120,
            "finished_at": now - 110,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 34_950_604,
            "cached_input_tokens": 22_393_100,
            "output_tokens": 113_528,
            "total_tokens": 35_064_132,
        },
        {
            "started_at": now - 90,
            "finished_at": now - 60,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 36_741_404,
            "cached_input_tokens": 23_241_990,
            "output_tokens": 114_588,
            "total_tokens": 36_855_992,
        },
    ]

    snapshot = module.usage_snapshot(entries, thread_id="bedrock-thread")

    assert snapshot["current_thread"]["turns"] == 2
    assert snapshot["current_thread"]["total_tokens"] == 1_791_860
    assert snapshot["current_thread"]["input_tokens"] == 1_790_800
    assert snapshot["current_thread"]["cached_input_tokens"] == 848_890
    assert snapshot["current_thread"]["output_tokens"] == 1_060
    assert snapshot["last_turn"]["total_tokens"] == 1_791_860
    assert snapshot["last_turn"]["raw_total_tokens"] == 36_855_992
    assert snapshot["last_turn"]["usage_meter_mode"] == "cumulative_delta"
    assert snapshot["recent"][0]["usage_meter_mode"] == "cumulative_baseline"
    assert snapshot["billing"]["sparkline"] == [0, 1_791_860]


def test_usage_snapshot_derives_cumulative_delta_across_tier_switch() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    entries = [
        {
            "started_at": now - 120,
            "finished_at": now - 110,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 34_950_604,
            "cached_input_tokens": 22_393_100,
            "output_tokens": 113_528,
            "total_tokens": 35_064_132,
        },
        {
            "started_at": now - 90,
            "finished_at": now - 60,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "flex",
            "success": True,
            "input_tokens": 36_741_404,
            "cached_input_tokens": 23_241_990,
            "output_tokens": 114_588,
            "total_tokens": 36_855_992,
        },
    ]

    snapshot = module.usage_snapshot(entries, thread_id="bedrock-thread")

    assert snapshot["current_thread"]["total_tokens"] == 1_791_860
    assert snapshot["last_turn"]["service_tier"] == "flex"
    assert snapshot["last_turn"]["usage_meter_mode"] == "cumulative_delta"
    assert snapshot["billing"]["service_tiers"]["default"]["total_tokens"] == 0
    assert snapshot["billing"]["service_tiers"]["flex"]["total_tokens"] == 1_791_860


def test_usage_snapshot_keeps_cumulative_baseline_across_zero_usage_rows() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    entries = [
        {
            "started_at": now - 180,
            "finished_at": now - 170,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 1_300_000_000,
            "cached_input_tokens": 1_250_000_000,
            "output_tokens": 3_000_000,
            "total_tokens": 1_303_000_000,
        },
        {
            "started_at": now - 120,
            "finished_at": now - 110,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        {
            "started_at": now - 80,
            "finished_at": now - 70,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 1_320_000_000,
            "cached_input_tokens": 1_269_500_000,
            "output_tokens": 3_050_000,
            "total_tokens": 1_323_050_000,
        },
    ]

    snapshot = module.usage_snapshot(entries, thread_id="bedrock-thread")

    assert snapshot["current_thread"]["turns"] == 3
    assert snapshot["current_thread"]["total_tokens"] == 20_050_000
    assert snapshot["last_turn"]["usage_meter_mode"] == "cumulative_delta"
    assert snapshot["last_turn"]["raw_total_tokens"] == 1_323_050_000
    assert snapshot["last_turn"]["total_tokens"] == 20_050_000
    assert snapshot["billing"]["last_24h_estimate"]["usd"] < 100


def test_usage_snapshot_does_not_bill_repeated_cumulative_counter() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    entries = [
        {
            "started_at": now - 180,
            "finished_at": now - 170,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 1_300_000_000,
            "cached_input_tokens": 1_250_000_000,
            "output_tokens": 3_000_000,
            "total_tokens": 1_303_000_000,
        },
        {
            "started_at": now - 80,
            "finished_at": now - 70,
            "thread_id": "bedrock-thread",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 1_300_000_000,
            "cached_input_tokens": 1_250_000_000,
            "output_tokens": 3_000_000,
            "total_tokens": 1_303_000_000,
        },
    ]

    snapshot = module.usage_snapshot(entries, thread_id="bedrock-thread")

    assert snapshot["current_thread"]["total_tokens"] == 0
    assert snapshot["last_turn"]["usage_meter_mode"] == "cumulative_baseline"
    assert snapshot["last_turn"]["raw_total_tokens"] == 1_303_000_000
    assert snapshot["billing"]["last_24h_estimate"]["usd"] == 0
    assert (
        snapshot["billing"]["last_24h_estimate"]["excluded_cumulative_baseline_entries"]
        == 2
    )


def test_usage_cost_estimates_use_mixed_tier_rate_cards() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    entries = [
        {
            "started_at": now - 50,
            "finished_at": now - 45,
            "thread_id": "standard",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "default",
            "success": True,
            "input_tokens": 200_000,
            "cached_input_tokens": 20_000,
            "output_tokens": 20_000,
            "total_tokens": 220_000,
        },
        {
            "started_at": now - 40,
            "finished_at": now - 35,
            "thread_id": "flex",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "flex",
            "success": True,
            "input_tokens": 200_000,
            "cached_input_tokens": 20_000,
            "output_tokens": 20_000,
            "total_tokens": 220_000,
        },
        {
            "started_at": now - 30,
            "finished_at": now - 25,
            "thread_id": "priority",
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "priority",
            "success": True,
            "input_tokens": 200_000,
            "cached_input_tokens": 20_000,
            "output_tokens": 20_000,
            "total_tokens": 220_000,
        },
    ]

    report = module.usage_billing_report(entries)

    assert report["totals_estimate"]["configured"] is True
    assert report["totals_estimate"]["credits_configured"] is True
    assert report["totals_estimate"]["approximate"] is True
    assert report["totals_estimate"]["rate_source"] == "mixed"
    assert report["totals_estimate"]["usd"] == 6.04
    assert report["totals_estimate"]["credits"] == 113.25
    assert report["totals_estimate"]["display_unit"] == "credits"
    assert report["rate_cards"]["gpt-5.5::default"]["input_usd_per_1m"] == 5.0
    assert report["rate_cards"]["gpt-5.5::flex"]["input_usd_per_1m"] == 2.5
    assert report["rate_cards"]["gpt-5.5::priority"]["input_usd_per_1m"] == 12.5


def test_usage_cost_estimate_prefers_observed_service_tier() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    report = module.usage_billing_report(
        [
            {
                "started_at": now - 10,
                "finished_at": now - 5,
                "thread_id": "resolved",
                "runtime": "codex",
                "model": "gpt-5.5",
                "service_tier": "priority",
                "observed_service_tier": "default",
                "success": True,
                "input_tokens": 200_000,
                "cached_input_tokens": 0,
                "output_tokens": 20_000,
                "total_tokens": 220_000,
            }
        ]
    )

    assert report["totals_estimate"]["usd"] == 1.6
    assert "gpt-5.5::default" in report["rate_cards"]
    assert "gpt-5.5::priority" not in report["rate_cards"]


def test_usage_cost_estimate_marks_gpt55_long_context_uplift() -> None:
    module = _load_agent_console_web()
    now = int(time.time())
    report = module.usage_billing_report(
        [
            {
                "started_at": now - 10,
                "finished_at": now - 5,
                "thread_id": "long-context",
                "runtime": "codex",
                "model": "gpt-5.5",
                "service_tier": "default",
                "success": True,
                "input_tokens": 300_000,
                "cached_input_tokens": 0,
                "output_tokens": 10_000,
                "total_tokens": 310_000,
            }
        ]
    )

    assert report["totals_estimate"]["long_context"] is True
    assert report["totals_estimate"]["usd"] == 3.45


def test_normalize_usage_entry_derives_nested_cached_and_reasoning_tokens() -> None:
    module = _load_agent_console_web()

    usage = module.normalize_usage_entry(
        {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 250},
            "output_tokens_details": {"reasoning_tokens": 75},
        }
    )

    assert usage["cached_input_tokens"] == 250
    assert usage["reasoning_output_tokens"] == 75
    assert usage["total_tokens"] == 1075


def test_codex_yield_diagnostics_classifies_short_stop_and_low_yield() -> None:
    module = _load_agent_console_web()

    short_stop = module.codex_yield_diagnostics(
        response="I'll inspect the repo and then run the checks.",
        error_text="",
        usage={"total_tokens": 50_000, "output_tokens": 39},
        success=False,
        promised_followup=True,
        continuation_incomplete=False,
        started_at=100,
        finished_at=105,
    )
    low_yield = module.codex_yield_diagnostics(
        response="DONE. Checked one command.",
        error_text="",
        usage={"total_tokens": 50_000, "output_tokens": 39},
        success=True,
        promised_followup=False,
        continuation_incomplete=False,
        started_at=100,
        finished_at=105,
    )
    zero_transport = module.codex_yield_diagnostics(
        response="",
        error_text="stream disconnected before completion",
        usage={
            "total_tokens": 0,
            "provider_error_kind": "bedrock_stream_disconnected",
            "zero_token_provider_failure": True,
        },
        success=False,
        promised_followup=False,
        continuation_incomplete=False,
        started_at=100,
        finished_at=119,
    )

    assert short_stop["provider_yield_kind"] == "short_stop"
    assert "final response promises future work" in short_stop["provider_yield_reasons"]
    assert low_yield["provider_yield_kind"] == "low_yield"
    assert "low output tokens: 39" in low_yield["provider_yield_reasons"]
    assert zero_transport["provider_yield_kind"] == "zero_transport"


def test_zero_token_provider_retry_allowed_is_side_effect_guarded() -> None:
    module = _load_agent_console_web()
    usage = {
        "provider_surface": "aws-bedrock",
        "provider_error_kind": "bedrock_stream_disconnected",
        "total_tokens": 0,
        "zero_token_provider_failure": True,
    }

    assert module.zero_token_provider_retry_allowed({"live_turn": {}}, usage) is True
    assert (
        module.zero_token_provider_retry_allowed(
            {"live_turn": {"last_tool": "shell", "file_interaction_count": 1}},
            usage,
        )
        is False
    )
    assert (
        module.zero_token_provider_retry_allowed(
            {"live_turn": {}}, {**usage, "provider_error_kind": "provider_rate_limited"}
        )
        is False
    )
    assert (
        module.zero_token_provider_retry_allowed(
            {"live_turn": {}}, {**usage, "total_tokens": 1}
        )
        is False
    )


def test_zero_token_provider_retry_pending_ignores_synthetic_checkpoint_response() -> (
    None
):
    module = _load_agent_console_web()
    module.WEB_PROMPT_ZERO_TOKEN_PROVIDER_MAX_RETRIES = 2
    usage = {
        "provider_surface": "aws-bedrock",
        "provider_error_kind": "codex_provider_error",
        "provider_error_text": (
            "unexpected status 404 Not Found: The model 'openai.gpt-5.5' "
            "does not exist, request id: req_example"
        ),
        "service_tier": "bedrock-failover",
        "total_tokens": 0,
        "zero_token_provider_failure": True,
    }

    assert module.zero_token_provider_retry_pending(
        "Provider recovery checkpoint\n\nCHECKPOINT",
        usage["provider_error_text"],
        usage,
        1,
    )
    assert (
        module.zero_token_provider_retry_service_tier("bedrock-failover", usage)
        == "flex"
    )
    assert not module.zero_token_provider_retry_pending(
        "Provider recovery checkpoint\n\nCHECKPOINT",
        usage["provider_error_text"],
        usage,
        2,
    )


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


def test_initial_context_meter_summarizes_context_sources() -> None:
    module = _load_agent_console_web()

    preview = module.context_pack_preview(
        {
            "history": [
                {
                    "prompt": "Older turn " + ("a" * 1800),
                    "response": "Older response " + ("b" * 2600),
                    "error": "",
                }
                for _ in range(12)
            ],
            "bbs": {
                "summary": "1 BBS pickup waiting",
                "activity": "Waiting on netops pickup",
            },
            "logs": "pytest passed\nmake lint passed\n" * 20,
            "pane": "worker idle\n" * 20,
            "usage": {"totals": {"turns": 12, "total_tokens": 12000}},
            "queue_depth": 0,
            "selected_model": "gpt-5.5",
        }
    )
    meter = module._initial_context_meter(
        {
            "history": [
                {
                    "prompt": "Review the runbook and keep going.",
                    "response": "The runbook requires a guarded restart.",
                }
            ],
            "queue": [{"prompt": "Follow up after the current run."}],
            "bbs": {
                "summary": "1 BBS pickup waiting",
                "activity": "Waiting on netops pickup",
            },
            "logs": "pytest passed\nmake lint passed",
            "pane": "worker idle",
            "draft_attachments": [
                {
                    "kind": "text",
                    "char_count": 1200,
                    "name": "notes.txt",
                }
            ],
            "usage": {"totals": {"turns": 1, "total_tokens": 1200}},
            "queue_depth": 1,
            "context_pack_preview": preview,
        }
    )

    assert "Context sources:" in meter["title"]
    assert "attachments" in meter["title"]
    assert "history" in meter["title"]
    assert "BBS" in meter["title"]
    assert "pack preview saves" in meter["title"]


def test_context_pack_preview_estimates_reference_packet_savings() -> None:
    module = _load_agent_console_web()

    preview = module.context_pack_preview(
        {
            "history": [
                {
                    "prompt": f"Runbook pass {index}: " + ("p" * 2000),
                    "response": f"Evidence and changes {index}: " + ("r" * 3600),
                    "error": "",
                }
                for index in range(18)
            ],
            "queued_prompts": [
                {"prompt": "Follow up after the current run and verify the ledger."}
            ],
            "bbs": {
                "state": "active",
                "summary": "Infra handoff active",
                "activity": "Waiting on Norman pickup",
                "top_threads": [{"title": "Bedrock cutover", "status": "open"}],
            },
            "logs": "lint passed\npytest passed\n" * 50,
            "pane": "OpenAI Codex ready\n" * 40,
            "usage": {
                "current_thread": {"turns": 18, "total_tokens": 110000},
                "totals": {"turns": 18, "total_tokens": 110000},
            },
            "accounting": {
                "billing_owner": "openbrand",
                "billing_project": "control-plane",
                "billing_unit": "work:control-plane",
            },
            "queue_depth": 1,
            "selected_model": "gpt-5.5",
        }
    )

    assert preview["schema"] == "norman.tui.context-pack-preview.v1"
    assert preview["behavior"] == "preview_only"
    assert preview["quality_gate"]["live_prompt_behavior_changed"] is False
    assert preview["quality_gate"]["requires_shadow_run_before_activation"] is True
    assert preview["current"]["tokens"] > preview["packed"]["tokens"]
    assert preview["savings"]["tokens"] > 0
    assert preview["savings"]["pct"] >= 25
    assert preview["savings"]["cost_range"]["configured"] is True
    assert preview["savings"]["cost_range"]["label"]
    assert any(
        item["label"] == "older turn bodies" for item in preview["excluded_sources"]
    )


def test_context_preflight_path_backs_large_text_attachments(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_CONTEXT_PREFLIGHT_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_CONTEXT_PREFLIGHT_ATTACHMENT_INLINE_CHARS", "900")
    monkeypatch.setenv("NORMAN_CODEX_CONTEXT_PREFLIGHT_ATTACHMENT_HEAD_CHARS", "360")
    monkeypatch.setenv("NORMAN_CODEX_CONTEXT_PREFLIGHT_ATTACHMENT_TAIL_CHARS", "220")
    module = _load_agent_console_web()

    body = "HEAD " + ("a" * 1500) + " middle-secret-marker " + ("z" * 1500) + " TAIL"
    attachment_path = tmp_path / "large-notes.txt"
    attachment_path.write_text(body, encoding="utf-8")
    prompt = module.build_prompt_with_attachments(
        "Review this without wasting tokens.",
        3,
        [
            {
                "token": "block-1",
                "name": "large-notes.txt",
                "path": str(attachment_path),
                "content_type": "text/plain",
                "size": len(body.encode("utf-8")),
                "kind": "text",
                "char_count": len(body),
            }
        ],
        model="gpt-5.5",
    )

    assert "[block-1] path-backed preview content:" in prompt
    assert "middle characters omitted from the prompt" in prompt
    assert "middle-secret-marker" not in prompt
    assert "Context preflight:" in prompt
    assert "Smart attachment previews saved" in prompt
    assert "inspect the listed file path" in prompt


def test_context_preflight_includes_sqlite_memory_refs(monkeypatch, tmp_path) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_CONTEXT_PREFLIGHT_ENABLED", "1")
    module = _load_agent_console_web()

    module.mirror_history_entry_to_state_db(
        {
            "thread_id": "thread-control-plane",
            "started_at": 1_780_000_000,
            "finished_at": 1_780_000_030,
            "runtime": "codex",
            "model": "gpt-5.5",
            "service_tier": "flex",
            "prompt": "Control plane Confluence runbook indexing and KPI cleanup.",
            "response": "Added runbook evidence pointers and billing tags.",
            "error": "",
            "usage": {"total_tokens": 1234},
        }
    )

    preflight = module.context_preflight_prompt_context(
        "Continue the control plane runbook KPI cleanup.",
        attachments=[],
        runtime="codex",
        model="gpt-5.5",
    )

    assert "Context preflight:" in preflight
    assert "Relevant local memory refs" in preflight
    assert "thread-control-plane" in preflight
    assert "Control plane Confluence runbook" in preflight


def test_context_preflight_labels_cumulative_usage_counters(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_CONTEXT_PREFLIGHT_ENABLED", "1")
    module = _load_agent_console_web()

    module.mirror_history_entry_to_state_db(
        {
            "thread_id": "thread-big-counter",
            "started_at": 1_780_000_000,
            "prompt": "Database driven TUI refresh accounting.",
            "response": "The refresh handoff kept local context.",
            "usage": {"total_tokens": 1_383_792_219},
        }
    )

    preflight = module.context_preflight_prompt_context(
        "Continue the database driven TUI refresh work.",
        attachments=[],
        runtime="codex",
        model="gpt-5.5",
    )

    assert "raw usage counter=1,383,792,219" in preflight
    assert "likely cumulative; not turn cost" in preflight


def test_tui_state_sqlite_mirrors_history_and_usage(monkeypatch, tmp_path) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()

    module.append_usage_entry(
        started_at=100,
        finished_at=130,
        thread_id="thread-1",
        speed="careful",
        detail=3,
        service_tier="default",
        success=True,
        runtime="codex",
        model="gpt-5.5",
        usage={
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "output_tokens": 50,
            "total_tokens": 1050,
            "provider_error_kind": "bedrock_stream_disconnected",
            "provider_yield_kind": "zero_transport",
            "provider_yield_reasons": ["zero-token provider failure"],
            "provider_request_ids": ["req-1"],
            "provider_trace_ids": ["trace-1"],
            "codex_returncode": 1,
            "zero_token_provider_failure": True,
        },
    )
    module.append_history_entry(
        prompt="Review the runbook and keep going.",
        response="The runbook requires a guarded restart.",
        error_text="",
        started_at=100,
        finished_at=130,
        thread_id="thread-1",
        speed="careful",
        detail=3,
        service_tier="default",
        runtime="codex",
        model="gpt-5.5",
        usage={
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "output_tokens": 50,
            "total_tokens": 1050,
        },
    )

    assert state_db.exists()
    with sqlite3.connect(state_db) as conn:
        turn = conn.execute(
            "SELECT thread_id, prompt_chars, response_chars, usage_total_tokens, success "
            "FROM turns"
        ).fetchone()
        usage = conn.execute(
            "SELECT thread_id, input_tokens, cached_input_tokens, output_tokens, "
            "total_tokens, charge_ledger_kind, charge_display_unit, charge_status, "
            "provider_yield_kind, provider_yield_reasons, "
            "provider_error_kind, provider_request_ids, provider_trace_ids, "
            "codex_returncode, "
            "zero_token_provider_failure "
            "FROM usage_events"
        ).fetchone()

    assert turn == (
        "thread-1",
        len("Review the runbook and keep going."),
        len("The runbook requires a guarded restart."),
        1050,
        1,
    )
    assert usage == (
        "thread-1",
        1000,
        200,
        50,
        1050,
        "chatgpt_codex_credit_estimate",
        "credits",
        "not_invoice_reconciled",
        "zero_transport",
        '["zero-token provider failure"]',
        "bedrock_stream_disconnected",
        '["req-1"]',
        '["trace-1"]',
        1,
        1,
    )


def test_audit_events_mirror_to_state_db(monkeypatch, tmp_path) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()

    module.append_audit_event(
        event_type="restart.handoff",
        summary="Context handoff ready.",
        detail="thread=abc123",
        severity="info",
        actor_type="system",
        thread_id="thread-1",
        event_at=123,
    )

    with sqlite3.connect(state_db) as conn:
        row = conn.execute(
            "SELECT event_type, event_at, summary, detail FROM audit_events"
        ).fetchone()

    assert row == ("restart.handoff", 123, "Context handoff ready.", "thread=abc123")


def test_bbs_permission_block_creates_deduped_human_intervention(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()
    monkeypatch.setattr(module, "now_ts", lambda: 456)

    snapshot = {
        "thread_id": "thread-local",
        "status_message": "BBS handoff blocked.",
        "last_error": "actor_not_allowed_for_target while posting th_glimpser_sms_media_endpoint_20260607 to glimpser",
        "last_response": "",
        "last_action_detail": "",
        "history": [],
    }

    first = module.detect_human_interventions(snapshot)
    second = module.detect_human_interventions(snapshot)
    interventions = module.load_human_interventions()

    assert len(first) == 1
    assert len(second) == 1
    assert len(interventions) == 1
    assert interventions[0]["kind"] == "bbs_permission_block"
    assert interventions[0]["severity"] == "ask_now"
    assert interventions[0]["target_actor"] == "glimpser"
    assert interventions[0]["thread_id"] == "th_glimpser_sms_media_endpoint_20260607"
    assert "BBS routing is blocked" in interventions[0]["question"]

    with sqlite3.connect(state_db) as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM human_interventions").fetchone()[
            0
        ]
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = ?",
            ("human_intervention.raised",),
        ).fetchone()[0]

    assert row_count == 1
    assert audit_count == 1


def test_human_gate_ignores_prior_advice_history(monkeypatch, tmp_path) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()

    snapshot = {
        "thread_id": "thread-current",
        "status_message": "Model process running.",
        "last_error": "",
        "last_response": (
            "For the screenshot: complete the sign-in/captcha/verification outside "
            "the model, then click Access done."
        ),
        "last_action_detail": "",
        "history": [
            {
                "prompt": "what do i do with this?",
                "response": "Complete the sign-in/captcha step, then retry.",
                "error": "",
            }
        ],
    }

    assert module.detect_human_interventions(snapshot) == []
    module.upsert_human_intervention(
        {
            "kind": "auth_or_human_gate",
            "severity": "ask_now",
            "fingerprint": "auth_or_human_gate:test:thread-current",
            "question": "A human gate appears to be blocking progress.",
            "detail": "Detected auth/captcha language in prior guidance.",
            "options": ["Complete the human gate now"],
            "evidence": {
                "thread_id": "thread-current",
                "text_preview": snapshot["last_response"],
            },
            "source_actor": "Norman",
            "thread_id": "thread-current",
        }
    )
    assert module.load_human_interventions() == []


def test_human_gate_uses_active_error_text(monkeypatch, tmp_path) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()

    snapshot = {
        "thread_id": "thread-current",
        "status_message": "Model process running.",
        "last_error": "Needs reauth before connector can continue.",
        "last_response": "",
        "last_action_detail": "",
        "history": [],
    }

    interventions = module.detect_human_interventions(snapshot)

    assert len(interventions) == 1
    assert interventions[0]["kind"] == "auth_or_human_gate"
    assert interventions[0]["thread_id"] == "thread-current"
    assert "Needs reauth" in interventions[0]["evidence"]["text_preview"]


def test_abandoned_restart_prompt_gets_specific_intervention(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()

    snapshot = {
        "thread_id": "thread-current",
        "status_message": "Model process running.",
        "last_error": "Needs reauth. Web prompt was abandoned after restart; no running model process was found.",
        "last_response": "",
        "last_action_detail": "",
        "history": [],
    }

    interventions = module.detect_human_interventions(snapshot)

    assert len(interventions) == 1
    assert interventions[0]["kind"] == "stale_web_prompt_after_restart"
    assert interventions[0]["fingerprint"].startswith("stale_web_prompt_after_restart:")
    assert not interventions[0]["fingerprint"].startswith("auth_or_human_gate:")
    assert "restart recovery state" in interventions[0]["detail"]
    assert "not automatically a provider" in interventions[0]["detail"]
    assert "Review the parked prompt details" in interventions[0]["options"]
    assert (
        "Retry the abandoned prompt as a new model turn" in interventions[0]["options"]
    )
    assert (
        "Web prompt was abandoned after restart"
        in interventions[0]["evidence"]["text_preview"]
    )


def test_empty_thread_human_gate_is_hidden_from_open_list(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    module = _load_agent_console_web()

    module.upsert_human_intervention(
        {
            "kind": "auth_or_human_gate",
            "severity": "ask_now",
            "fingerprint": "auth_or_human_gate:test:",
            "question": "A human gate appears to be blocking progress.",
            "detail": "Needs reauth.",
            "options": ["Complete the human gate now"],
            "evidence": {"thread_id": ""},
            "source_actor": "Norman",
            "thread_id": "",
        }
    )

    assert module.load_human_interventions() == []


def test_sentinel_defaults_to_observe_only_zero_llm_budget(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_SENTINEL_MODE", "observe_only")
    monkeypatch.setenv("NORMAN_CODEX_SENTINEL_ACTIONS_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_SENTINEL_LLM_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_SENTINEL_MAX_LLM_TOKENS_PER_DAY", "0")
    module = _load_agent_console_web()
    monkeypatch.setattr(module, "now_ts", lambda: 1000)

    sentinel = module.build_sentinel_state(
        {
            "pending": False,
            "queue_depth": 0,
            "web_worker_alive": False,
            "model_process_alive": False,
            "active_child_pid": 0,
        },
        {"state": "idle", "signals": []},
    )

    assert sentinel["mode"] == "observe_only"
    assert sentinel["state"] == "healthy_idle"
    assert sentinel["severity"] == "quiet_log"
    assert sentinel["actions_enabled"] is False
    assert sentinel["observe_only"] is True
    assert sentinel["llm_enabled"] is False
    assert sentinel["sms_enabled"] is False
    assert sentinel["spend_guardrail"]["max_llm_tokens_per_day"] == 0
    assert sentinel["spend_guardrail"]["estimated_llm_tokens_this_tick"] == 0


def test_sentinel_wedged_state_raises_one_observe_only_intervention(
    monkeypatch, tmp_path
) -> None:
    state_dir = tmp_path / "web-bridge"
    state_db = tmp_path / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(state_dir))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(state_db))
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_ENABLED", "1")
    monkeypatch.setenv("NORMAN_CODEX_SENTINEL_MODE", "observe_only")
    monkeypatch.setenv("NORMAN_CODEX_SENTINEL_PENDING_NO_WORKER_SECONDS", "90")
    module = _load_agent_console_web()
    monkeypatch.setattr(module, "now_ts", lambda: 1_000)
    state_dir.mkdir(parents=True, exist_ok=True)
    module.THREAD_ID_PATH.write_text("thread-sentinel", encoding="utf-8")

    sentinel = module.build_sentinel_state(
        {
            "pending": True,
            "last_started_at": 800,
            "queue_depth": 0,
            "web_worker_alive": False,
            "model_process_alive": False,
            "active_child_pid": 0,
        },
        {"state": "working", "signals": []},
    )
    first = module.maybe_raise_sentinel_intervention(sentinel)
    second = module.maybe_raise_sentinel_intervention(sentinel)
    interventions = module.load_human_interventions()

    assert sentinel["state"] == "wedged"
    assert sentinel["severity"] == "ask_now"
    assert sentinel["actions_enabled"] is False
    assert first is not None
    assert second is not None
    assert len(interventions) == 1
    assert interventions[0]["kind"] == "sentinel_wedged"
    assert "Observe-only sentinel" in interventions[0]["detail"]

    with sqlite3.connect(state_db) as conn:
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = ?",
            ("human_intervention.raised",),
        ).fetchone()[0]
    assert audit_count == 1


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
    assert "function contextSourceBreakdown(snapshot)" in source
    assert "function contextCarryCostDescriptor(sourceBreakdown, snapshot)" in source
    assert "function contextPackPreviewState(snapshot)" in source
    assert "Context pack dry run" in source
    assert "preview only; live prompt assembly is unchanged" in source
    assert "function estimateContextTokensFromText(value)" in source
    assert "function estimateAttachmentContextTokens(attachments)" in source
    assert "Context sources:" in source
    assert "Estimated carried-context input cost:" in source
    assert "Projected pack cost savings:" in source
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


def test_composer_prompt_box_uses_larger_mobile_and_desktop_targets() -> None:
    source = _agent_console_web_source()
    shell_match = re.search(
        r"\.composer-input-shell \{\{(?P<body>.*?)\n    \}\}", source, re.S
    )
    action_match = re.search(
        r"\.composer-inline-action \{\{(?P<body>.*?)\n    \}\}", source, re.S
    )
    send_match = re.search(r"\.composer-send \{\{(?P<body>.*?)\n    \}\}", source, re.S)
    mobile_compose_match = re.search(
        r"body\.mobile-compose-mode \.composer-input-shell \{\{(?P<body>.*?)\n      \}\}",
        source,
        re.S,
    )

    assert (
        'id="prompt-input" name="message" rows="1" autocomplete="off" '
        'autocapitalize="sentences" spellcheck="true" enterkeyhint="send"'
    ) in source
    assert shell_match
    assert (
        "grid-template-rows: auto auto auto minmax(52px, auto);"
        in shell_match.group("body")
    )
    assert "padding: 10px 11px;" in shell_match.group("body")
    assert "border-radius: 12px;" in shell_match.group("body")
    assert "cursor: text;" in shell_match.group("body")
    assert ".composer-input-shell:focus-within textarea {{" in source
    assert ".composer-inline-action:active {{" in source
    assert ".composer-send:active {{" in source
    assert action_match
    assert "width: 36px;" in action_match.group("body")
    assert "min-height: 36px;" in action_match.group("body")
    assert send_match
    assert "width: 38px;" in send_match.group("body")
    assert "min-height: 38px;" in send_match.group("body")
    assert mobile_compose_match
    assert (
        "grid-template-rows: auto auto auto minmax(54px, auto);"
        in mobile_compose_match.group("body")
    )
    assert 'body[data-layout-mode="tile"] .composer-inline-action' in source
    assert "width: 32px;" in source
    assert "min-width: 210px;" in source


def test_composer_interrupt_uses_vertical_confirmed_rail() -> None:
    source = _agent_console_web_source()

    assert 'id="interrupt-submit-button"' in source
    assert ".composer-send-cluster {{" in source
    assert "flex-direction: column;" in source
    assert ".composer-send-queue {{" in source
    assert ".composer-send-interrupt.confirming {{" in source
    assert "interruptSubmitConfirmUntil: 0" in source
    assert "function armInterruptSubmitConfirm(message) {{" in source
    assert "Interrupt armed for 4s. Tap ↑ again to confirm" in source
    assert (
        'void submitAsk(event, {{ interlaceMode: "interrupt", interruptConfirmed: true }})'
        in source
    )


def test_composer_prompt_shell_click_focuses_textarea() -> None:
    source = _agent_console_web_source()

    assert (
        'const composerInputShell = el.askForm.querySelector(".composer-input-shell");'
        in source
    )
    assert 'composerInputShell.addEventListener("click", (event) =>' in source
    assert (
        "target.closest(\"button, input, select, textarea, a, [role='button'], "
        '[data-upload-action]")'
    ) in source
    assert "focusPromptInputAtEnd();" in source
    assert "setUploadMenuOpen(false);" in source


def test_mobile_composer_keyboard_mode_has_native_sized_controls() -> None:
    source = _agent_console_web_source()

    assert "body.mobile-keyboard-open .composer-input-shell {{" in source
    assert "backdrop-filter: blur(14px) saturate(116%);" in source
    assert "body.mobile-compose-mode .composer-toolbar {{" in source
    assert "width: calc(100vw - 16px);" in source
    assert "max-width: calc(100vw - 16px);" in source
    assert "body.mobile-compose-mode .composer-upload-menu {{" in source
    assert "min-width: min(86vw, 240px);" in source
    assert "body.mobile-compose-mode .composer-upload-item {{" in source
    assert "min-height: 38px;" in source
    assert "body.mobile-compose-mode textarea {{" in source
    assert "font-size: 16px;" in source
    assert ".composer-send:disabled," in source


def test_settings_drawer_uses_crisp_stacked_route_layout() -> None:
    source = _agent_console_web_source()

    assert "width: min(calc(100vw - 24px), 560px);" in source
    assert "grid-template-rows: auto minmax(0, 1fr);" in source
    assert ".settings-body {{" in source
    assert "scrollbar-gutter: stable;" in source
    assert "grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));" in source
    assert ".settings-card .quick-link {{" in source
    assert ".model-route-matrix-head {{" in source
    assert "display: none;" in source
    assert "grid-template-areas:" in source
    assert '"main status"' in source
    assert '"model status"' in source
    assert '"detail detail"' in source
    assert "-webkit-line-clamp: 2;" in source


def test_prompt_focus_settles_mobile_composer_viewport() -> None:
    source = _agent_console_web_source()
    settle_match = re.search(
        r"function settleComposerAfterPromptFocus\(\) \{\{(?P<body>.*?)\n    \}\}",
        source,
        re.S,
    )
    focus_match = re.search(
        r'el\.promptInput\.addEventListener\("focus", \(\) => \{\{(?P<body>.*?)\n    \}\}\);',
        source,
        re.S,
    )
    input_match = re.search(
        r'el\.promptInput\.addEventListener\("input", \(\) => \{\{(?P<body>.*?)\n    \}\}\);',
        source,
        re.S,
    )

    assert "function settleComposerAfterPromptFocus() {{" in source
    assert "[60, 180, 320].forEach((delayMs) => {{" in source
    assert settle_match
    assert "scheduleComposerReserve();" in settle_match.group("body")
    assert "scrollIntoView" not in settle_match.group("body")
    assert "stickConversationToBottom" not in settle_match.group("body")
    assert focus_match
    assert "settleComposerAfterPromptFocus();" in focus_match.group("body")
    assert input_match
    assert "scheduleComposerReserve();" in input_match.group("body")
    assert "preserveLiveEdge: true" not in input_match.group("body")


def test_topbar_controls_keep_right_aligned_tactile_layout() -> None:
    source = _agent_console_web_source()

    assert ".topbar-actions {{" in source
    assert "margin-left: auto;" in source
    assert "flex-wrap: nowrap;" in source
    assert ".topbar-actions .utility-button," in source
    assert "gap: 5px;" in source
    assert ".topbar-menu-button {{" in source
    assert "justify-content: center;" in source
    assert "@media (max-width: 979px) {{" in source
    assert "justify-content: flex-end;" in source


def test_tui_polish_pass_bumps_visible_ui_version() -> None:
    source = _agent_console_web_source()

    assert 'DEFAULT_UI_VERSION = "2026.06.16.4"' in source


def test_tui_disables_xfast_outside_emergency_gate() -> None:
    source = _agent_console_web_source()

    assert "EMERGENCY_XFAST_ENABLED = any(" in source
    assert '"NORMAN_CODEX_EMERGENCY_XFAST_ENABLED"' in source
    assert 'return "fast" if EMERGENCY_XFAST_ENABLED else "balanced"' in source
    assert 'type="range" min="2" max="3"' in source
    assert "Think Std/medium ↔ Deep/xhigh" in source
    assert "Fast/low ↔ Deep/xhigh" not in source
    assert 'return EMERGENCY_XFAST_ENABLED ? "fast" : "balanced";' in source
    assert 'if (index <= 1) return "fast";' not in source


def test_tui_keeps_append_only_usage_ledger_for_cost_receipts() -> None:
    source = _agent_console_web_source()

    assert 'NORMAN_CODEX_WEB_USAGE_ITEMS", "1000"' in source
    assert "MAX_USAGE_LEDGER_ITEMS" in source
    assert "USAGE_LEDGER_PATH" in source
    assert "usage-ledger.jsonl" in source
    assert '"accounting_version": "norman.tui-usage.v2"' in source
    assert "def usage_accounting_tags() -> dict[str, str]:" in source
    assert '"billing_scope": usage_billing_scope()' in source
    assert '"billing_unit": usage_billing_unit()' in source
    assert '"billing_project": usage_billing_project()' in source
    assert '"accounting": usage_accounting_tags()' in source
    assert "def append_usage_ledger_entry" in source
    assert "append_usage_ledger_entry(usage_entry)" in source
    assert '"schema": "norman.tui.billing.v1"' in source
    assert "def usage_billing_report" in source
    assert "def usage_charge_ledger_kind" in source
    assert "charge_ledger_kind" in source
    assert "charge_display_unit" in source
    assert "charge_status" in source
    assert "function inferChargeLedgerKind" in source
    assert "function codexCreditRatesForModel" in source
    assert "function chargeBasisState" in source
    assert "Charge basis" in source
    assert "Codex estimate" in source
    assert 'data-cost-tone="credits"' in source
    assert "API-dollar equivalent hidden from chip" in source
    assert "billingCapsuleState(snapshot)" in source
    assert "not a credit-card charge" in source
    assert "kpi-capsule-sparkline" in source
    assert "Cost Explorer attribution requires" in source
    assert "ROUTE_RECEIPT_PATH" in source
    assert "NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED" in source
    assert "live_tui_shadow_route" in source
    assert "baseline_all_5_5_cost_usd" in source
    assert "def build_route_receipt" in source
    assert "def append_route_receipt_entry" in source
    assert "append_route_receipt(" in source


def test_mobile_attachment_chips_use_touch_sized_horizontal_rail() -> None:
    source = _agent_console_web_source()

    assert ".draft-attachments:not([hidden]) {{" in source
    assert "min-height: 34px;" in source
    assert "scroll-snap-type: x proximity;" in source
    assert "max-width: min(78vw, 280px);" in source
    assert "min-height: 34px;" in source
    assert ".attachment-chip-link {{" in source
    assert "min-height: 28px;" in source
    assert ".attachment-remove {{" in source
    assert "width: 28px;" in source
    assert "min-width: 28px;" in source


def test_mobile_message_actions_have_touch_targets_without_full_width_buttons() -> None:
    source = _agent_console_web_source()

    assert ".message-tools-toggle {{" in source
    assert "min-width: 28px;" in source
    assert "min-height: 28px;" in source
    assert ".message-footer .copy-button," in source
    assert ".message-footer .relay-target {{" in source
    assert "width: auto;" in source
    assert "min-height: 32px;" in source
    assert "white-space: nowrap;" in source
    assert ".reply-tail-action {{" in source
    assert "min-height: 30px;" in source


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
    assert "NORMAN_CODEX_RUNNING_NO_OUTPUT_SECONDS" in source
    assert "running_no_output" in source
    assert 'class="primary composer-send composer-send-queue" data-icon="→"' in source
    assert 'class="ghost composer-send composer-send-interrupt" data-icon="↑"' in source
    assert 'class="composer-send-label">Queue</span>' in source
    assert "confirmInterruptSubmit" in source


def test_agent_console_template_exposes_per_agent_microtexture_tokens() -> None:
    source = _agent_console_web_source()

    assert "AGENT_TEXTURE_OVERRIDES" in source
    assert "# BEGIN GENERATED TUI MICROTEXTURE OVERRIDES" in source
    assert "# END GENERATED TUI MICROTEXTURE OVERRIDES" in source
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
    assert '"dohio": "shared"' in source
    assert '"networking": "shared"' in source
    assert '"netops": "shared"' in source
    assert '"panelbot": {\n        "texture-angle": "0deg"' in source
    assert '"cloudagent": {\n        "texture-angle": "62deg"' in source
    assert '"dohio": {\n        "texture-angle": "145deg"' in source
    assert '"networking": {\n        "texture-angle": "90deg"' in source
    assert "AGENT_ACCENT_OVERRIDES[_slug] = dict(WORK_BOT_ACCENT)" not in source
    assert "repeating-linear-gradient(\n          var(--texture-angle)" in source
    assert "var(--brand-wash-opacity)" in source
    assert "var(--focus-detail-opacity)" in source
    assert '"composer-detail-opacity"' in source
    assert '"composer-cross-detail-opacity"' in source
    assert '"message-detail-opacity"' in source
    assert '"texture-glow-x"' in source
    assert '"identity-line-opacity"' in source
    assert '"identity-cross-opacity"' in source
    assert '"identity-dot-opacity"' in source
    assert '"identity-rail-opacity"' in source
    assert '"identity-band-opacity"' in source
    assert "max(var(--composer-detail-opacity), 0.058)" in source
    assert "max(var(--composer-cross-detail-opacity), 0.026)" in source
    assert "max(var(--message-detail-opacity), 0.032)" in source
    assert "var(--agent-accent-3)" in source
    assert "var(--texture-glow-x) var(--texture-glow-y)" in source
    assert "var(--identity-line-opacity)" in source
    assert "var(--identity-cross-opacity)" in source
    assert "var(--identity-dot-opacity)" in source
    assert "var(--identity-rail-opacity)" in source
    assert "var(--identity-band-opacity)" in source
    assert "@keyframes microtexture-proof-life" in source
    assert "@keyframes microtexture-chrome-breathe" in source
    assert "@keyframes microtexture-wind-shine" in source
    assert "@keyframes microtexture-flow" in source
    assert "@keyframes microtexture-watch" in source
    assert "@keyframes microtexture-blocked-jitter" in source
    assert "--microtexture-drift-duration: 64s;" in source
    assert (
        "animation: microtexture-chrome-breathe var(--microtexture-drift-duration)"
        in source
    )
    assert 'body[data-microtexture-state="active"] .topbar.surface::before' in source
    assert 'body[data-microtexture-state="watch"] .topbar.surface::before' in source
    assert 'body[data-microtexture-state="flow"] .topbar.surface::before' in source
    assert 'body[data-microtexture-state="idle"] .topbar.surface::before' not in source
    assert 'body[data-microtexture-state="idle"]::before' in source
    assert 'body[data-microtexture-state="active"]::before' in source
    assert 'body[data-microtexture-state="flow"]::before' in source
    assert 'body[data-microtexture-state="watch"]::before' in source
    assert 'body[data-microtexture-state="blocked"]::before' in source
    assert 'body[data-microtexture-state="stalled"]::before' in source
    assert "prefers-reduced-motion: reduce" in source
    assert "function microtextureProofState" in source
    assert "snapshot.live_turn" in source
    assert 'return "flow";' in source
    assert "document.body.dataset.microtextureState = microtextureProofState" in source
    assert "@media (min-width: 1440px)" in source
    assert "max-width: none;" in source
    assert "width: min(100%, 1480px);" in source
    assert "--conversation-lane: 1120px;" in source
    assert "@media (min-width: 1800px)" in source
    assert "width: min(100%, 1720px);" in source
    assert "--conversation-lane: 1320px;" in source


def test_static_directory_microtextures_follow_contact_sheet_tokens() -> None:
    home_source = _home_js_source()
    systems_source = _systems_js_source()
    styles_source = _styles_source()
    reference_cards = _texture_reference_cards()

    expected_source_slugs = {
        "norman": "norman",
        "switchboard": "norman",
        "panelbot": "panelbot",
        "cloudagent": "cloudagent",
        "dohio": "dohio",
        "networking": "netops",
        "compere": "keystone",
        "platinum-standard": "platinum-standard",
    }

    for source in (home_source, systems_source):
        assert "// BEGIN GENERATED TUI MICROTEXTURES" in source
        assert "// END GENERATED TUI MICROTEXTURES" in source
        for runtime_slug, reference_slug in expected_source_slugs.items():
            card = reference_cards[reference_slug]
            assert (
                f"'{runtime_slug}': {{ angle: {card['angle']}, "
                f"crossAngle: {card['cross']}, grain: {card['grain']}"
            ) in source
        assert "accent: 'rgba(117, 208, 198, 0.052)'" in source

    assert "--dohio-microtexture-image" in styles_source
    assert '.fleet-card[data-service-slug="dohio"]::before' in styles_source


def test_tui_microtexture_generated_sections_are_current() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/sync_tui_microtextures.py", "--check"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_tui_visual_capture_script_writes_header_composer_states(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/capture_tui_visual_states.py",
            "--html-only",
            "--agents",
            "panelbot,dohio",
            "--states",
            "idle,attachments",
            "--viewports",
            "mobile",
            "--out-dir",
            str(tmp_path),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["html_only"] is True
    assert len(manifest["entries"]) == 4
    html_source = (tmp_path / "panelbot-attachments-mobile.html").read_text(
        encoding="utf-8"
    )
    assert 'id="agent-title" class="brand-title" aria-label="PanelBot"' in html_source
    assert 'id="prompt-input"' in html_source
    assert "window.__TUI_VISUAL_CAPTURE__" in html_source
    assert 'document.body.dataset.visualState = "attachments";' in html_source
    assert "prompt.focus({ preventScroll: true });" in html_source


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
    assert module.entity_mark_for_label("NetOps") == "NE"
    assert module.entity_mark_for_label("networking") == "NW"
    assert module.entity_mark_for_label("Networking Host") == "NW"
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


def test_render_initial_inline_markup_promotes_outcome_sigils() -> None:
    module = _load_agent_console_web()

    rendered = module._render_initial_inline_markup(
        "DONE. Checked one thing.\nBLOCKED: missing approval.\nCHECKPOINT remaining work.",
        token="open-sesame",
        profile="personal-2",
        route="host",
    )

    assert rendered.count('class="outcome-sigil"') == 3
    assert 'data-outcome="done"' in rendered
    assert 'data-outcome="blocked"' in rendered
    assert 'data-outcome="checkpoint"' in rendered
    assert 'data-mark="DN"' in rendered
    assert 'data-mark="BL"' in rendered
    assert 'data-mark="CP"' in rendered
    assert "Final status: DONE" in rendered


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


def test_render_initial_inline_markup_expands_relative_tui_file_paths(
    monkeypatch, tmp_path: Path
) -> None:
    workdir = tmp_path / "control_plane"
    monkeypatch.setenv("NORMAN_CODEX_WORKDIR", str(workdir))
    module = _load_agent_console_web()

    artifact = workdir / "artifacts" / "perplexity" / "confluence-sync-status.md"
    script = workdir / "scripts" / "runbook_confluence_sync.py"
    rendered = module._render_initial_inline_markup(
        (
            "Updated `artifacts/perplexity/confluence-sync-status.md` and "
            "[sync script](scripts/runbook_confluence_sync.py)."
        ),
        token="open-sesame",
        profile="personal-2",
        route="host",
    )

    assert f"<code>{artifact}</code>" in rendered
    assert str(script) in rendered
    assert "/api/file?" in rendered
    assert "path=%2F" in rendered
    assert "<code>artifacts/perplexity/confluence-sync-status.md</code>" not in rendered


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


def test_render_file_view_embeds_media_players_for_audio_and_video() -> None:
    module = _load_agent_console_web()
    tempdir = Path(tempfile.mkdtemp())
    video = tempdir / "clip.mp4"
    audio = tempdir / "clip.mp3"
    video.write_bytes(b"not-real-video")
    audio.write_bytes(b"not-real-audio")

    video_handler = _make_handler(module)
    module.Handler.render_file_view(
        video_handler,
        video,
        "video/mp4",
        video.stat(),
        {"profile": ["slate"]},
    )
    video_rendered = video_handler.wfile.getvalue().decode("utf-8")

    assert "<video controls" in video_rendered
    assert 'preload="metadata"' in video_rendered
    assert "<source " in video_rendered
    assert 'type="video/mp4"' in video_rendered
    assert "Preview is not available" not in video_rendered

    audio_handler = _make_handler(module)
    module.Handler.render_file_view(
        audio_handler,
        audio,
        "audio/mpeg",
        audio.stat(),
        {"profile": ["slate"]},
    )
    audio_rendered = audio_handler.wfile.getvalue().decode("utf-8")

    assert "<audio controls" in audio_rendered
    assert 'preload="metadata"' in audio_rendered
    assert "<source " in audio_rendered
    assert 'type="audio/mpeg"' in audio_rendered
    assert "Preview is not available" not in audio_rendered


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
    assert "cp.kris.openbrand.com" in rendered
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
    assert "https://dj.home.arpa/?token=demo-token" in rendered
    assert "toy-box.home.arpa:8793" in rendered
    assert "192.168.2.146:8793" in rendered


def test_toy_box_sync_uses_lan_ssh_without_changing_published_hosts() -> None:
    module = _load_sync_agent_console_template()

    host = module.HOSTS["toy-box"]

    assert host.ssh_target == "root@192.168.2.146"
    assert host.public_host == "toy-box.home.arpa"
    assert host.lan_host == "192.168.2.146"
    assert "toy-box.tail94915.ts.net" in host.alias_hosts


def test_host_home_urls_use_norman_host_route() -> None:
    module = _load_sync_agent_console_template()

    urls = module.host_home_urls(module.HOSTS["norman"])

    assert ("norman.home.arpa", "http://norman.home.arpa/host/") in urls
    assert ("norman.tail94915.ts.net", "http://norman.tail94915.ts.net/host/") in urls


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
    assert "scout.kris.openbrand.com" in source
    assert '"phone-ops": ("phone", "phoneops")' in source
    assert '"dj": ("dj", "yt")' in source
    assert '"studio": ("studio", "camera-studio")' in source
    assert '"tv": ("tv",)' in source
    assert "def bot_host_groups" in source
    assert 'host.endswith(".kris.openbrand.com")' in source
    assert "BOT_PUBLIC_INTERNAL_TLS_NAMES" in source


def test_bot_proxy_caddy_uses_internal_tls_for_pending_public_work_aliases(
    monkeypatch,
) -> None:
    module = _load_bot_proxy_renderer()
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered = module.render_hosts()

    assert "# compere" in rendered
    assert "keystone.kris.openbrand.com {\n    tls internal" in rendered
    assert "infra.kris.openbrand.com {\n    tls internal" in rendered
    assert (
        "kpis.kris.openbrand.com, leadership.kris.openbrand.com {\n    tls internal"
        in rendered
    )
    assert "scout.kris.openbrand.com {\n    tls internal" in rendered
    assert (
        "dashboards.kris.openbrand.com, tmi.kris.openbrand.com {\n    tls internal"
        in rendered
    )
    assert (
        "cp.kris.openbrand.com, control.kris.openbrand.com {\n    tls internal"
        not in rendered
    )
    assert "goldbook.kris.openbrand.com {\n    tls internal" not in rendered
    assert "platinum.kris.openbrand.com {\n    tls internal" not in rendered
    assert "phone.home.arpa, phoneops.home.arpa {\n    tls internal" in rendered


def test_bot_proxy_caddy_ip_gates_knox_local_work_aliases(monkeypatch) -> None:
    module = _load_bot_proxy_renderer()
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered = module.render_hosts()

    assert (
        "@knox_allowed remote_ip 127.0.0.1/32 ::1/128 192.168.2.1/32 "
        "192.168.2.241/32 100.103.34.17/32 "
        "fd7a:115c:a1e0::3438:2211/128 192.168.2.136/32 100.78.41.73/32 "
        "fd7a:115c:a1e0::4d33:2949/128 192.168.2.137/32 "
        "100.112.62.71/32 192.168.2.140/32 100.109.202.7/32 "
        "192.168.2.141/32 100.77.147.57/32" in rendered
    )
    assert 'respond "forbidden" 403' in rendered
    assert (
        "keystone.kris.openbrand.com {\n"
        "    tls internal\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "infra.kris.openbrand.com {\n"
        "    tls internal\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "panelbot.kris.openbrand.com {\n"
        "    tls internal\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    panelbot_block = re.search(
        r"^panelbot\.kris\.openbrand\.com \{(?P<body>.*?)\n\}",
        rendered,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert panelbot_block
    assert "100.77.147.57/32" in panelbot_block.group("body")
    infra_block = re.search(
        r"^infra\.kris\.openbrand\.com \{(?P<body>.*?)\n\}",
        rendered,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert infra_block
    assert "100.77.147.57/32" in infra_block.group("body")
    kpis_block = re.search(
        r"^kpis\.kris\.openbrand\.com, leadership\.kris\.openbrand\.com \{(?P<body>.*?)\n\}",
        rendered,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert kpis_block
    assert "192.168.2.141/32" in kpis_block.group("body")
    assert "100.77.147.57/32" in kpis_block.group("body")
    assert (
        "mls.kris.openbrand.com {\n" "    tls internal\n" "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "scout.kris.openbrand.com {\n"
        "    tls internal\n"
        "    @knox_allowed remote_ip"
    ) in rendered
    assert (
        "cp.kris.openbrand.com, control.kris.openbrand.com {\n"
        "    @knox_allowed remote_ip" not in rendered
    )
    assert "goldbook.kris.openbrand.com {\n    @knox_allowed remote_ip" not in rendered
    assert "platinum.kris.openbrand.com {\n    @knox_allowed remote_ip" not in rendered


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
            "norman": Host("192.168.2.241"),
            "work-special": Host("192.168.2.147"),
        },
    )
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered_dns = module.render_dns_json()

    assert '"mc.kris.openbrand.com": "192.168.2.241"' in rendered_dns
    assert '"market.kris.openbrand.com": "192.168.2.241"' in rendered_dns
    assert '"mc.home.arpa": "192.168.2.241"' in rendered_dns
    assert '"market.home.arpa": "192.168.2.241"' in rendered_dns


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
            "norman": Host("192.168.2.241"),
            "toy-box": Host("192.168.2.146"),
        },
    )
    monkeypatch.setattr(
        module,
        "discover_all_instances",
        lambda: ({}, {"housebot": Instance()}),
    )

    rendered_dns = module.render_dns_json("tailnet")

    assert '"housebot.home.arpa": "100.103.34.17"' in rendered_dns
    assert '"bbs.home.arpa": "100.103.34.17"' in rendered_dns
    assert '"switchboard.home.arpa": "100.103.34.17"' in rendered_dns


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
            "norman": Host("192.168.2.241"),
            "toy-box": Host("192.168.2.146"),
            "hal": Host("192.168.2.137"),
            "private-host": Host("192.168.2.148"),
            "networking-host": Host("192.168.2.242"),
            "work-special": Host("192.168.2.147"),
        },
    )
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered_hosts = module.render_hosts()
    rendered_dns = module.render_dns_json("tailnet")

    assert "housebot.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.2.146:8787" in rendered_hosts
    assert "diamond-roc.home.arpa, diamondroc.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.2.146:8796" in rendered_hosts
    assert "eyebat.home.arpa, eyeball.home.arpa" in rendered_hosts
    assert "networking.home.arpa, netbot.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.2.242:8791" in rendered_hosts
    assert "phone.home.arpa, phoneops.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.2.146:8790" in rendered_hosts
    assert '"housebot.home.arpa": "100.103.34.17"' in rendered_dns
    assert '"diamond-roc.home.arpa": "100.103.34.17"' in rendered_dns
    assert '"networking.home.arpa": "100.103.34.17"' in rendered_dns
    assert '"phone.home.arpa": "100.103.34.17"' in rendered_dns
    assert rendered_hosts.count("mc.kris.openbrand.com") == 2


def test_bot_proxy_caddy_exposes_switchboard_with_legacy_aliases(monkeypatch) -> None:
    module = _load_bot_proxy_renderer()
    monkeypatch.setattr(module, "discover_all_instances", lambda: ({}, {}))

    rendered_paths = module.render_paths()
    rendered_hosts = module.render_hosts()

    assert "# subprime" in rendered_paths
    assert "redir /bot/subprime /bot/subprime/ 308" in rendered_paths
    assert "# switchboard" in rendered_paths
    assert "redir /bot/switchboard /bot/switchboard/ 308" in rendered_paths
    assert "reverse_proxy 192.168.2.241:8765" in rendered_paths

    assert "# switchboard" in rendered_hosts
    assert "switchboard.home.arpa" in rendered_hosts
    assert "switchboard.norman.home.arpa" in rendered_hosts
    assert "subprime.home.arpa" in rendered_hosts
    assert "subprime.norman.home.arpa" in rendered_hosts
    assert "botprime.home.arpa" in rendered_hosts
    assert "bot.norman.home.arpa" in rendered_hosts
    assert "reverse_proxy 192.168.2.241:8765" in rendered_hosts


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
    assert "reverse_proxy 192.168.2.241:8765" in rendered_hosts


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
            "norman": Host("192.168.2.241"),
            "toy-box": Host("192.168.2.146"),
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
    assert "reverse_proxy 192.168.2.146:8788" in rendered_hosts
    assert '"eyebat.home.arpa": "192.168.2.241"' in rendered_dns
    assert '"eyeball.home.arpa": "192.168.2.241"' in rendered_dns
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
        assert "goldbook.kris.openbrand.com" in source
        assert "platinum.kris.openbrand.com" in source
        assert "keystone.kris.openbrand.com" in source
        assert "infra.kris.openbrand.com" in source
        assert "kpis.kris.openbrand.com" in source
        assert "dashboards.kris.openbrand.com" in source
        assert "mls.kris.openbrand.com" in source
        assert "scout.kris.openbrand.com" in source
        assert "publisher.kris.openbrand.com" not in source


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
        codex_home="/home/operator/.codex-control-plane",
    )

    assert module.instance_public_host(instance) == "cp.kris.openbrand.com"
    urls = module.instance_console_urls(instance)
    assert urls["url"] == (
        "https://cp.kris.openbrand.com/?token=demo-token&profile={profile}"
    )
    assert urls["tail_url"] == (
        "http://work-special.tail94915.ts.net:8783/?token=demo-token&profile={profile}"
    )


def test_sync_template_prefers_phone_ops_console_route() -> None:
    module = _load_sync_agent_console_template()
    source = _sync_agent_console_template_source()

    instance = module.ConsoleInstance(
        name="phone-ops",
        host_name="toy-box",
        ssh_target="root@192.168.2.146",
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

    assert module.instance_public_host(instance) == "phone.home.arpa"
    assert '"phone-ops": ("phone.home.arpa", "phoneops.home.arpa")' in source
    assert module.instance_console_urls(instance)["url"] == (
        "https://phone.home.arpa/?token=demo-token&profile={profile}"
    )


def test_sync_template_prefers_vanity_proxy_console_routes_for_home_tuis() -> None:
    module = _load_sync_agent_console_template()

    housebot = module.ConsoleInstance(
        name="housebot",
        host_name="toy-box",
        ssh_target="root@192.168.2.146",
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
        ssh_target="root@example.invalid",
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
        "http://toy-box.tail94915.ts.net:8787/?token=house-token&profile={profile}"
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
        ssh_target="root@192.168.2.241",
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
        ssh_target="root@example.invalid",
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
        ("compere", "keystone.kris.openbrand.com"),
        ("infra", "infra.kris.openbrand.com"),
        ("leadership-kpis", "kpis.kris.openbrand.com"),
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
            codex_home=f"/home/operator/.codex-{name}",
        )
        assert module.instance_public_host(instance) == expected


def test_sync_template_archives_publisher_tui() -> None:
    module = _load_sync_agent_console_template()

    assert "publisher" in module.ARCHIVED_INSTANCE_NAMES
    assert "studio" not in module.ARCHIVED_INSTANCE_NAMES
    assert "tv" not in module.ARCHIVED_INSTANCE_NAMES


def test_sync_template_treats_hal_as_root_managed_local_host() -> None:
    module = _load_sync_agent_console_template()

    hal = module.HOSTS["hal"]

    assert hal.local is True
    assert hal.read_only is False
    assert hal.root_managed_local is True
    assert hal.ssh_target.startswith("root@")


def test_sync_template_root_managed_hal_only_skips_when_local(monkeypatch) -> None:
    module = _load_sync_agent_console_template()

    hal = module.HOSTS["hal"]

    monkeypatch.setattr(module, "_current_host_tokens", lambda: {"norman"})
    assert module.host_runs_locally(hal) is False

    monkeypatch.setattr(module, "_current_host_tokens", lambda: {"hal"})
    assert module.host_runs_locally(hal) is True


def test_sync_template_uses_root_ssh_for_norman() -> None:
    module = _load_sync_agent_console_template()

    norman = module.HOSTS["norman"]

    assert norman.local is False
    assert norman.ssh_target.startswith("root@")


def test_sync_template_source_skips_root_managed_local_host_in_user_sync() -> None:
    source = _sync_agent_console_template_source()

    assert "if host.root_managed_local and host_runs_locally(host):" in source
    assert (
        "root-managed local host; skipping local template/env writes in user sync"
        in source
    )


def test_sync_template_restart_requires_explicit_flag() -> None:
    module = _load_sync_agent_console_template()

    default_args = module.parse_args([])
    restart_args = module.parse_args(["--restart"])
    compat_copy_only_args = module.parse_args(["--no-restart"])
    forced_restart_args = module.parse_args(["--restart", "--force-restart"])

    assert default_args.restart is False
    assert default_args.no_restart is False
    assert restart_args.restart is True
    assert compat_copy_only_args.restart is False
    assert compat_copy_only_args.no_restart is True
    assert forced_restart_args.restart is True
    assert forced_restart_args.force_restart is True


def test_sync_template_restart_guard_blocks_active_status() -> None:
    module = _load_sync_agent_console_template()

    reason = module._status_restart_block_reason(
        {
            "active_child_pid": 1234,
            "queue_depth": 2,
            "current_prompt_id": "prompt-1",
            "pending": True,
            "state": "running",
        }
    )

    assert "active child pid 1234" in reason
    assert "queue depth 2" in reason
    assert "active job prompt-1" in reason
    assert "pending prompt" in reason
    assert "state running" in reason
    assert (
        module._status_restart_block_reason(
            {"active_child_pid": 0, "queue_depth": 0, "status": "idle"}
        )
        == ""
    )


def test_sync_template_health_check_retries_without_curl_noise() -> None:
    source = _sync_agent_console_template_source()

    assert "NORMAN_SYNC_HEALTH_ATTEMPTS" in source
    assert (
        'if output=$(curl -fsS --max-time "$TIMEOUT_SECONDS" "$URL" '
        "2>&1 >/dev/null); then"
    ) in source
    assert 'last_error="$output"' in source
    assert "health ok after %s/%s attempts" in source
    assert "health check failed on port %s after %s attempts" in source


def test_sync_template_restarts_serially_with_per_tui_health_gate() -> None:
    source = _sync_agent_console_template_source()

    assert "NORMAN_SYNC_RESTART_SETTLE_SECONDS" in source
    assert "def restart_and_health_check_instances" in source
    assert "for index, instance in enumerate(instances, start=1):" in source
    assert "restart_instances(host, [instance])" in source
    assert "health_check_instances(host, [instance])" in source
    assert "serial restart queue" in source


def test_local_sync_systemd_units_target_hal() -> None:
    service = _systemd_unit_source("norman-agent-console-sync-local.service")
    path = _systemd_unit_source("norman-agent-console-sync-local.path")
    timer = _systemd_unit_source("norman-agent-console-sync-local.timer")

    assert "sync_agent_console_template.py --targets hal" in service
    assert "--no-restart" in service
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
    old_host = os.environ.get("NORMAN_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("NORMAN_CODEX_LOCAL_HOST_ALIASES")
    try:
        os.environ["NORMAN_CODEX_CANONICAL_HOST"] = "cp.kris.openbrand.com"
        os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = (
            "cp.kris.openbrand.com,work-special.home.arpa,192.168.2.147"
        )
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("NORMAN_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["NORMAN_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("NORMAN_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = old_aliases

    assert module.canonical_origin_components() == (
        "https",
        "cp.kris.openbrand.com",
    )


def test_canonical_origin_uses_http_for_home_arpa_hosts() -> None:
    old_host = os.environ.get("NORMAN_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("NORMAN_CODEX_LOCAL_HOST_ALIASES")
    try:
        os.environ["NORMAN_CODEX_CANONICAL_HOST"] = "work-special.home.arpa"
        os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = (
            "work-special.home.arpa,192.168.2.147"
        )
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("NORMAN_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["NORMAN_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("NORMAN_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = old_aliases

    assert module.canonical_origin_components() == (
        "http",
        f"work-special.home.arpa:{module.PORT}",
    )


def test_should_redirect_canonical_without_query_token_for_public_work_host() -> None:
    old_host = os.environ.get("NORMAN_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("NORMAN_CODEX_LOCAL_HOST_ALIASES")
    old_token = os.environ.get("NORMAN_CODEX_WEB_TOKEN")
    try:
        os.environ["NORMAN_CODEX_CANONICAL_HOST"] = "cp.kris.openbrand.com"
        os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = (
            "work-special.home.arpa,192.168.2.147"
        )
        os.environ["NORMAN_CODEX_WEB_TOKEN"] = "demo-token"
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("NORMAN_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["NORMAN_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("NORMAN_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = old_aliases
        if old_token is None:
            os.environ.pop("NORMAN_CODEX_WEB_TOKEN", None)
        else:
            os.environ["NORMAN_CODEX_WEB_TOKEN"] = old_token

    handler = object.__new__(module.Handler)
    handler.headers = {"Host": "work-special.home.arpa:8783"}
    handler.client_address = ("192.168.2.50", 12345)

    parsed = module.urlparse("http://work-special.home.arpa:8783/?profile=slate")

    assert module.Handler.should_redirect_canonical(
        handler,
        parsed,
        {"profile": ["slate"]},
    )


def test_render_console_link_url_keeps_sibling_service_hostnames() -> None:
    old_host = os.environ.get("NORMAN_CODEX_CANONICAL_HOST")
    old_aliases = os.environ.get("NORMAN_CODEX_LOCAL_HOST_ALIASES")
    old_port = os.environ.get("NORMAN_CODEX_WEB_PORT")
    try:
        os.environ["NORMAN_CODEX_CANONICAL_HOST"] = "dj.home.arpa"
        os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = (
            "dj.home.arpa,toy-box.home.arpa,192.168.2.146"
        )
        os.environ["NORMAN_CODEX_WEB_PORT"] = "8793"
        module = _load_agent_console_web()
    finally:
        if old_host is None:
            os.environ.pop("NORMAN_CODEX_CANONICAL_HOST", None)
        else:
            os.environ["NORMAN_CODEX_CANONICAL_HOST"] = old_host
        if old_aliases is None:
            os.environ.pop("NORMAN_CODEX_LOCAL_HOST_ALIASES", None)
        else:
            os.environ["NORMAN_CODEX_LOCAL_HOST_ALIASES"] = old_aliases
        if old_port is None:
            os.environ.pop("NORMAN_CODEX_WEB_PORT", None)
        else:
            os.environ["NORMAN_CODEX_WEB_PORT"] = old_port

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


def test_render_console_link_url_falls_back_to_tail_when_remote_from_lan_only_host() -> (
    None
):
    module = _load_agent_console_web()
    link = {
        "url": "http://toy-box.home.arpa:8793/?token={token}&profile={profile}",
        "lan_url": "http://192.168.2.146:8793/?token={token}&profile={profile}",
        "tail_url": "http://toy-box.tail94915.ts.net:8793/?token={token}&profile={profile}",
    }

    remote_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="cp.kris.openbrand.com",
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
        request_host="cp.kris.openbrand.com",
        route_mode="lan",
    )

    assert remote_rendered == (
        "http://toy-box.tail94915.ts.net:8793/?token=demo-token&profile=slate"
    )
    assert lan_rendered == "http://192.168.2.146:8793/?token=demo-token&profile=slate"
    assert stale_lan_rendered.startswith("http://toy-box.tail94915.ts.net:8793/")
    assert "route=lan" in stale_lan_rendered


def test_render_console_link_url_prefers_tail_for_tailnet_client_on_home_arpa() -> None:
    module = _load_agent_console_web()
    link = {
        "url": "https://housebot.home.arpa/?token={token}&profile={profile}",
        "lan_url": "http://192.168.2.146:8787/?token={token}&profile={profile}",
        "tail_url": "http://toy-box.tail94915.ts.net:8787/?token={token}&profile={profile}",
    }

    tailnet_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="norman.home.arpa",
        route_mode="auto",
        client_ip="100.78.41.73",
    )
    lan_rendered = module.render_console_link_url(
        link,
        token="demo-token",
        profile="slate",
        request_host="norman.home.arpa",
        route_mode="auto",
        client_ip="192.168.2.136",
    )

    assert tailnet_rendered == (
        "http://toy-box.tail94915.ts.net:8787/?token=demo-token&profile=slate"
    )
    assert lan_rendered == "http://192.168.2.146:8787/?token=demo-token&profile=slate"


def test_render_console_link_url_supports_explicit_tail_route() -> None:
    module = _load_agent_console_web()

    rendered = module.render_console_link_url(
        {
            "url": "https://cp.kris.openbrand.com/?token={token}&profile={profile}",
            "lan_url": "http://192.168.2.147:8783/?token={token}&profile={profile}",
            "tail_url": "http://work-special.tail94915.ts.net:8783/?token={token}&profile={profile}",
        },
        token="demo-token",
        profile="slate",
        request_host="work-special.home.arpa",
        route_mode="tail",
    )

    assert rendered.startswith("http://work-special.tail94915.ts.net:8783/")
    assert "token=demo-token" in rendered
    assert "profile=slate" in rendered
    assert "route=tail" in rendered
