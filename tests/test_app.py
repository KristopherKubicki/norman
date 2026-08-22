from fastapi.testclient import TestClient
from pathlib import Path
import pytest

from app import crud
from app.core.auth_cache import clear_auth_caches


def _create_admin_user(db) -> None:
    crud.user.create_admin_user(
        db,
        email="admin@example.com",
        password="pass123",
        username="admin",
    )
    clear_auth_caches()


def test_home_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root endpoint should redirect unauthenticated users to login."""
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {
        "/login.html?next=%2F",
        "/setup.html",
    }


def test_root_renders_norman_bridge_when_auth_disabled(
    test_app: TestClient,
) -> None:
    response = test_app.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert 'id="norman-bridge"' in response.text
    assert 'id="cockpit-group-list"' in response.text
    assert 'id="cockpit-workspace-button"' in response.text
    assert 'class="cockpit-groups"' not in response.text
    assert 'id="cockpit-thread-field"' in response.text
    assert 'id="cockpit-token-meter"' in response.text
    assert 'id="bridge-icon-route"' in response.text
    assert 'id="bridge-icon-user-plus"' in response.text
    assert response.text.count('class="cockpit-icon"') >= 12
    assert 'id="norman-favicon"' in response.text
    assert "/static/favicon.svg?v=20260822a" in response.text
    assert "/static/css/bridge.css?v=20260822k" in response.text
    assert "/static/js/bridge.js?v=20260822k" in response.text
    assert "site-banner" not in response.text
    assert 'id="global-status-bar"' not in response.text


def test_bridge_route_renders_grouped_agent_workspace(
    test_app: TestClient,
) -> None:
    response = test_app.get("/bridge.html", follow_redirects=False)
    assert response.status_code == 200
    assert 'id="cockpit-domains"' in response.text
    assert 'id="cockpit-command-rail"' not in response.text
    assert 'class="cockpit-command-rail"' in response.text
    assert 'id="cockpit-composer"' in response.text
    assert 'id="cockpit-rooms"' in response.text
    assert 'id="bridge-room-dialog"' in response.text
    assert "Direct messages" in response.text
    assert "/static/js/bridge.js" in response.text
    assert "Message Personal" not in response.text


def test_legacy_cockpit_routes_redirect_to_bridge(test_app: TestClient) -> None:
    for path in ("/cockpit", "/cockpit.html"):
        response = test_app.get(path, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/bridge"


def test_bridge_client_derives_boundaries_from_estate_registry() -> None:
    source = Path("app/static/js/bridge.js").read_text(encoding="utf-8")
    styles = Path("app/static/css/bridge.css").read_text(encoding="utf-8")
    assert "function normalizeGroups(estate)" in source
    assert "merged.set('norman'" in source
    assert "function groupedAgents" in source
    assert "function directoryGroup" in source
    assert "function botIdentityTileHtml" in source
    assert "function roomIdentityStackHtml" in source
    assert "principal: group.slug" in source
    assert "domain: domain?.slug" in source
    assert "source: 'norman_bridge'" in source
    assert "bridge_conversation_id" in source
    assert "function selectConversation" in source
    assert "function createRoom" in source
    assert "function jobObjective(job)" in source
    assert "recipientRow: el('cockpit-recipient-row')" in source
    assert "composeMeta: el('cockpit-compose-meta')" in source
    assert "function composerGuidance" in source
    assert "Restoring ${name}'s thread" in source
    assert "function normalizeBridgeResponse(text)" in source
    assert "Prior Bridge status" not in source
    assert "function startBootActivity()" in source
    assert "bridge-boot-activity" in source
    assert 'data-chip="usage"' in source
    assert 'data-chip="spend"' in source
    assert "function formatCompactNumber" in source
    assert "download=1" in source
    assert "...state.conversations.filter((item) => item._local_only)" in source
    assert "First paint never depends on the network." in source
    assert "60000 + Math.floor(Math.random() * 30000)" in source
    assert "document.visibilityState === 'visible'" in source
    assert "function provisionalAgents()" in source
    assert "_statusDelayed: true" in source
    assert "live ? `${live} live` : `${known} known`" in source
    assert "{ timeoutMs: 180000 }" in source
    assert "fetchJson(`${API}/estate/overview`, { timeoutMs: 12000 })" in source
    assert "function hydrateConversationActivities(conversation)" in source
    assert "/model\\.delta/.test(event.event_type || '')" in source
    assert "execution\\.advisory_only/.test(type)) return 'running'" in source
    assert "LOCAL_CONVERSATIONS_KEY" in source
    assert "function loadLocalConversations" in source
    assert "function persistConversationLocally" in source
    assert "function mergeConversations" in source
    assert "class BridgeRequestError" in source
    assert "Log in to sync and run this conversation." in source
    assert "Saved on this device" in source
    assert "Could not open direct message" not in source
    assert "WORK_PRINCIPALS" not in source
    assert "INFRA_PATTERN" not in source
    assert "Message Personal" not in source
    assert "PROFILE_PALETTES" in source
    assert "function fontRoles" in source
    assert "function patternDetail" in source
    assert "--texture-cross-angle" in source
    assert "new URLSearchParams(window.location.search).get('agent')" in source
    assert "texture?.mark || displaySlug(slug)" in source
    assert "function workingMessageHtml" in source
    assert 'class="cockpit-presence"' in source
    assert 'class="cockpit-turn"' in source
    assert 'class="cockpit-event-stack"' in source
    assert "function promptPhaseForStatus" in source
    assert "function promptPhaseForEvent" in source
    assert "function resumeTopicPrompts()" in source
    assert "function draftResumePrompt(prompt)" in source
    assert 'data-resume-prompt="${escapeHtml(prompt)}"' in source
    assert "function iconHtml" in source
    assert "TEXTURE_MOTION_PROFILES" in source
    assert "function textureMotionSignature" in source
    assert "IDENTITY_GLYPHS" in source
    assert "function identityGlyphFor" in source
    assert "function agentSkeletonHtml" in source
    assert "function setWorkspaceMenuOpen" in source
    assert "bootstrapped: false" in source
    assert "bridge-simple-cartouche--hero" in source
    assert "data-motion=" in source
    assert "root.dataset.identityMotion" in source
    assert "function textureFractalWave" in source
    assert "function interpolatedTextureProfile" in source
    assert "function addTextureInput" in source
    assert "root.addEventListener('pointermove'" in source
    assert "root.addEventListener('keydown'" in source
    assert "state.texture.inputEnergy" in source
    assert "state.texture.disturbances" in source
    assert "state.texture.targetX" in source
    assert "const travelingWake" in source
    assert "connectJobEventStream(created.job_id)" in source
    assert "selectJob(created.job_id)" not in source
    assert "cockpit-presence__sweep" not in source
    assert "cockpit-working__signal" in source
    assert "cockpit-working__progress" in source
    assert "function updateBootInterstitial" in source
    assert "function normalizeBridgeResponse" in source
    assert 'data-entity-key="artmonster"' in styles
    assert "bridge-boot-interstitial" in styles
    assert "--radius-panel" in styles
    assert "--thread-item-gap" in styles
    assert ".cockpit-presence__nodes i:nth-child(4)" in styles
    assert ".cockpit-turn__messages" in styles
    assert ".cockpit-send span" in styles
    assert ".cockpit-resume-prompts" in styles
    assert ".cockpit-resume-prompt" in styles
    assert '[data-prompt-state="running"] .cockpit-thread-field' in styles
    assert ".cockpit-icon-sprite" in styles
    assert "bridge-icon-breathe" in styles
    assert ".cockpit-working__signal" in styles
    assert "clip-path: inset(0 0 0 100%)" in styles
    assert ".bridge-directory-group__head" in styles
    assert ".bridge-bot-group__grid" in styles
    assert '.bridge-simple-cartouche[data-variant="signal"]' in styles
    assert '.bridge-simple-cartouche[data-variant="editorial"]' in styles
    assert "@keyframes bridge-cartouche-drift" in styles
    assert "@keyframes bridge-cartouche-orbit" in styles
    assert "@keyframes bridge-cartouche-halftone" in styles
    assert '.bridge-simple-cartouche[data-motion="masonry"]' in styles
    assert ".entity-cartouche__glyph" in styles
    assert ".bridge-simple-cartouche--hero" in styles
    assert "Sidebar scroll ownership" in styles
    assert ".cockpit-section--agents .cockpit-nav-list" in styles
    assert "scrollbar-gutter: stable" in styles
    assert "grid-template-areas:" in styles
    assert '"warning"' in styles
    assert "grid-area: feed" in styles
    assert "grid-area: composer" in styles


def test_bridge_loads_the_tui_font_roles() -> None:
    source = Path("app/templates/base.html").read_text(encoding="utf-8")

    assert "family=IBM+Plex+Mono" in source
    assert "family=IBM+Plex+Sans+Condensed" in source
    assert "family=IBM+Plex+Serif" in source
    assert "family=Poppins" in source


def test_root_redirects_switchboard_host_to_switchboard_dashboard(
    test_app: TestClient,
) -> None:
    response = test_app.get(
        "/",
        follow_redirects=False,
        headers={"Host": "switchboard.home.arpa"},
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard.html?view=switchboard"


def test_dashboard_embed_hides_global_chrome(test_app: TestClient) -> None:
    response = test_app.get("/dashboard.html?embed=1", follow_redirects=False)
    assert response.status_code == 200
    assert "Norman Prime" in response.text
    assert "site-banner" not in response.text
    assert 'id="global-status-bar"' not in response.text


def test_switchboard_route_redirects_to_switchboard_dashboard(
    test_app: TestClient,
) -> None:
    response = test_app.get("/switchboard.html", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard.html?view=switchboard"


def test_bots_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/bots.html", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {"/login.html", "/setup.html"}


def test_consoles_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/consoles.html", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {"/login.html", "/setup.html"}


def test_systems_page_requires_login(
    test_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    response = test_app.get("/systems.html", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] in {"/login.html", "/setup.html"}


def test_invalid_auth_cookie_redirects_to_login_and_clears_cookie(
    test_app: TestClient, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_AUTH_MIDDLEWARE_IN_TESTS", "1")
    _create_admin_user(db)

    response = test_app.get(
        "/dashboard.html",
        cookies={"access_token": "definitely-invalid"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login.html?next=%2Fdashboard.html"
    assert 'access_token=""' in response.headers.get("set-cookie", "")


def test_bridge_distinguishes_authentication_from_runtime_availability(
    test_app: TestClient,
) -> None:
    response = test_app.get("/bridge", follow_redirects=False)

    assert response.status_code == 200
    bridge_js = Path("app/static/js/bridge.js").read_text()
    assert "Login required" in bridge_js
    assert "Log in to connect Norman" in bridge_js
    assert "function isStalePendingJob" in bridge_js
    assert "function recentBridgeRuntimeJobs" in bridge_js
    assert (
        "Bridge execution did not start; canceled to prevent a stale queued job."
        in bridge_js
    )
    assert "Runtime is control-only" not in bridge_js
