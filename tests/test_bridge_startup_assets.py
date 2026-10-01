"""Keep the chat startup path independent of external asset hosts."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def test_bridge_uses_local_styles_without_unused_external_scripts():
    """Chat can render and start when external CDNs are unreachable."""
    env = Environment(loader=FileSystemLoader(Path("app/templates")))
    html = env.get_template("bridge.html").render(
        settings={},
        active_page="bridge",
        show_navbar=False,
        show_statusbar=False,
        user_email="test@example.invalid",
    )
    assert "/static/vendor/bootstrap/bootstrap-5.3.0.min.css" in html
    assert "cdn.jsdelivr.net" not in html
    assert "fonts.googleapis.com" not in html
    assert "approvals_badge.js" not in html
    assert "/static/js/bridge.js" in html


def test_other_pages_keep_their_existing_framework_assets():
    """The chat optimization does not remove other pages' UI dependencies."""
    env = Environment(loader=FileSystemLoader(Path("app/templates")))
    html = env.get_template("base.html").render(
        settings={},
        active_page="settings",
        show_navbar=False,
        show_statusbar=False,
        user_email="test@example.invalid",
    )
    assert "bootstrap.bundle.min.js" in html
    assert "approvals_badge.js" in html
