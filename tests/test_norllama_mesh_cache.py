from app.services.norllama import mesh_cache


def test_mesh_cache_returns_fresh_hit(monkeypatch):
    mesh_cache.reset_mesh_cache()
    calls = []

    def fake_build_mesh_overview(timeout_seconds=None):
        calls.append(timeout_seconds)
        return {
            "schema": "norman.norllama.mesh.v1",
            "status": "ok",
            "healthy_worker_count": 3,
        }

    monkeypatch.setattr(
        mesh_cache.gateway, "build_mesh_overview", fake_build_mesh_overview
    )

    first = mesh_cache.get_mesh_overview(timeout_seconds=2, ttl_seconds=60)
    second = mesh_cache.get_mesh_overview(timeout_seconds=2, ttl_seconds=60)

    assert first["cache"]["status"] == "refresh"
    assert second["cache"]["status"] == "hit"
    assert calls == [2]


def test_mesh_cache_can_force_refresh(monkeypatch):
    mesh_cache.reset_mesh_cache()
    counter = {"count": 0}

    def fake_build_mesh_overview(timeout_seconds=None):
        counter["count"] += 1
        return {
            "schema": "norman.norllama.mesh.v1",
            "status": "ok",
            "count": counter["count"],
        }

    monkeypatch.setattr(
        mesh_cache.gateway, "build_mesh_overview", fake_build_mesh_overview
    )

    first = mesh_cache.get_mesh_overview(ttl_seconds=60)
    second = mesh_cache.get_mesh_overview(force_refresh=True, ttl_seconds=60)

    assert first["count"] == 1
    assert second["count"] == 2
    assert second["cache"]["status"] == "refresh"


def test_mesh_cache_returns_stale_snapshot_on_refresh_error(monkeypatch):
    mesh_cache.reset_mesh_cache()
    calls = {"count": 0}

    def fake_build_mesh_overview(timeout_seconds=None):
        calls["count"] += 1
        if calls["count"] > 1:
            raise RuntimeError("frontdoor unavailable")
        return {
            "schema": "norman.norllama.mesh.v1",
            "status": "ok",
            "healthy_worker_count": 2,
        }

    monkeypatch.setattr(
        mesh_cache.gateway, "build_mesh_overview", fake_build_mesh_overview
    )

    mesh_cache.get_mesh_overview(ttl_seconds=0, stale_seconds=60)
    stale = mesh_cache.get_mesh_overview(ttl_seconds=0, stale_seconds=60)

    assert stale["status"] == "ok"
    assert stale["cache"]["status"] == "stale_error"
    assert "frontdoor unavailable" in stale["cache"]["last_error"]
