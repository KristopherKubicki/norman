from pathlib import Path


def _messages_log_template_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "messages_log.html"
    ).read_text(encoding="utf-8")


def _messages_log_js_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "js"
        / "messages_log.js"
    ).read_text(encoding="utf-8")


def test_messages_log_template_includes_secret_stash_panel() -> None:
    source = _messages_log_template_source()

    assert 'id="streams-secret-toggle"' in source
    assert 'id="streams-secret-panel"' in source
    assert 'id="streams-secret-label"' in source
    assert 'id="streams-secret-value"' in source
    assert 'id="streams-secret-stash"' in source
    assert 'id="streams-secret-stash-only"' in source
    assert 'id="streams-secret-visibility"' in source
    assert 'id="streams-secret-draft-meta"' in source
    assert 'id="streams-secret-list"' in source


def test_messages_log_template_keeps_header_controls_compact() -> None:
    source = _messages_log_template_source()

    assert ">Prime</a>" in source
    assert ">Dir</a>" in source
    assert 'id="streams-thread-toggle"' in source
    assert "Switch between thread and feed views" in source
    assert 'id="streams-simple-toggle"' in source
    assert "\n        Menu\n" in source
    assert 'id="streams-focus-toggle"' in source
    assert "streams-advanced-control" in source


def test_messages_log_template_keeps_active_thread_header_compact() -> None:
    source = _messages_log_template_source()

    assert 'id="messages-conversation-header"' in source
    assert 'class="messages-conversation-primary"' in source
    assert 'class="messages-conversation-rail"' in source
    assert 'class="messages-conversation-pill"' in source
    assert "messages-conversation-value--primary" in source


def test_messages_log_js_wires_secret_stash_api_and_paste_capture() -> None:
    source = _messages_log_js_source()

    assert "/api/v1/keys/stash" in source
    assert "function maybeCaptureSensitivePaste" in source
    assert "function concealSecretDraft" in source
    assert "function revealSecretDraft" in source
    assert "function copyTextToClipboard" in source
    assert "stageSecretDraft(" in source
    assert "desktopToggle.textContent = streamsSimpleMode ? 'Menu' : 'Close';" in source
    assert "button.textContent = 'Switch';" in source
    assert "input.addEventListener('paste'" in source
    assert "consoleInput.addEventListener('paste'" in source


def test_messages_log_js_masks_sensitive_content_in_render_paths() -> None:
    source = _messages_log_js_source()

    assert "function renderMaskedPlainText" in source
    assert "function renderMaskedPreformattedText" in source
    assert "text.innerHTML = renderMaskedPlainText" in source
    assert "output.innerHTML = renderMaskedPreformattedText" in source
    assert "body.innerHTML = segment.type === 'meta'" in source
