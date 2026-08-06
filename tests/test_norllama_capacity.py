from app.services.norllama import capacity


MODEL = capacity.HEAVY_CODING_MODEL


def _worker(
    worker_id,
    *,
    reachable=True,
    models=None,
    role="production",
    status="ok",
):
    return {
        "id": worker_id,
        "role": role,
        "memory_gb": 128 if worker_id.startswith("spark") else 16,
        "reachable": reachable,
        "status": status,
        "models": list(models if models is not None else [MODEL]),
    }


def _mesh(*, frontdoor_reachable=True, workers=None, cache_status="refresh"):
    return {
        "frontdoor": {
            "reachable": frontdoor_reachable,
            "status": "ok" if frontdoor_reachable else "error",
            "models": [MODEL],
        },
        "workers": list(workers or []),
        "cache": {
            "status": cache_status,
            "age_seconds": 0,
            "ttl_seconds": 15,
        },
    }


def _snapshot(mesh, **kwargs):
    return capacity.build_capacity_snapshot(
        mesh,
        requested_model="norman-code",
        selected_model=MODEL,
        **kwargs,
    )


def test_heavy_coding_capacity_requires_a_reachable_spark_with_the_model():
    snapshot = _snapshot(
        _mesh(
            workers=[
                _worker(
                    "mac-mini-133",
                    role="fallback",
                    models=[MODEL],
                ),
                _worker("spark-150", reachable=False),
                _worker("spark-151", reachable=True),
            ]
        )
    )

    assert snapshot["available"] is True
    assert snapshot["reason"] == "available"
    assert [worker["id"] for worker in snapshot["eligible_workers"]] == [
        "spark-150",
        "spark-151",
    ]
    assert snapshot["ineligible_workers"] == [
        {
            "id": "mac-mini-133",
            "role": "fallback",
            "memory_gb": 16,
            "reachable": True,
            "status": "ok",
            "model_advertised": True,
            "reason": "ineligible_for_heavy_coding",
        }
    ]
    assert snapshot["cloud_fallback"] is True


def test_heavy_coding_capacity_distinguishes_unavailable_conditions():
    cases = [
        (
            "no_eligible_workers_configured",
            _mesh(
                workers=[
                    _worker(
                        "mac-mini-133",
                        role="fallback",
                        models=[MODEL],
                    )
                ]
            ),
        ),
        (
            "no_eligible_worker_reachable",
            _mesh(
                workers=[
                    _worker("spark-150", reachable=False, status="error"),
                    _worker("spark-151", reachable=False, status="error"),
                ]
            ),
        ),
        (
            "model_not_available_on_eligible_workers",
            _mesh(
                workers=[
                    _worker("spark-150", models=[]),
                    _worker("spark-151", models=[]),
                ]
            ),
        ),
        (
            "local_frontdoor_unreachable",
            _mesh(
                frontdoor_reachable=False,
                workers=[_worker("spark-150")],
            ),
        ),
        (
            "mesh_probe_stale",
            _mesh(
                workers=[_worker("spark-150")],
                cache_status="stale_error",
            ),
        ),
    ]

    for expected_reason, mesh in cases:
        snapshot = _snapshot(mesh)
        assert snapshot["available"] is False
        assert snapshot["reason"] == expected_reason
        assert snapshot["retryable"] is True


def test_failed_mesh_probe_has_a_safe_unavailable_capacity_contract():
    snapshot = capacity.unavailable_capacity_snapshot(
        requested_model="norman-code",
        selected_model=MODEL,
        reason="mesh_probe_failed",
    )

    assert snapshot == {
        "schema": "norman.norllama.capacity.v1",
        "available": False,
        "reason": "mesh_probe_failed",
        "requested_model": "norman-code",
        "selected_model": MODEL,
        "frontdoor": {
            "reachable": False,
            "status": "unknown",
            "model_advertised": False,
        },
        "eligible_workers": [
            {"id": "spark-150", "role": "production"},
            {"id": "spark-151", "role": "production"},
        ],
        "ineligible_workers": [
            {
                "id": "mac-mini-133",
                "reason": "ineligible_for_heavy_coding",
            }
        ],
        "cache": {"status": "unavailable"},
        "cloud_fallback": True,
        "retryable": True,
    }


def test_recent_model_timeout_blocks_capacity_until_a_later_success():
    timeout = {
        "recorded_at": 1000,
        "status": "timeout",
        "ok": False,
        "model": MODEL,
        "reason": "local_model_timeout",
    }
    timed_out = _snapshot(
        _mesh(workers=[_worker("spark-150")]),
        route_outcomes=[timeout],
        now=1050,
    )

    assert timed_out["available"] is False
    assert timed_out["reason"] == "recent_local_model_timeout"
    assert timed_out["retryable"] is True
    assert timed_out["cooldown"] == {
        "active": True,
        "model": MODEL,
        "endpoint": "",
        "status": "timeout",
        "reason": "local_model_timeout",
        "recorded_at": 1000,
        "age_seconds": 50,
        "cooldown_seconds": 60,
        "remaining_seconds": 10,
        "worker_id": "",
        "worker_endpoint": "",
        "upstream": "",
    }

    recovered = _snapshot(
        _mesh(workers=[_worker("spark-150")]),
        route_outcomes=[
            timeout,
            {
                "recorded_at": 1010,
                "status": "ok",
                "ok": True,
                "model": MODEL,
            },
        ],
        now=1050,
    )

    assert recovered["available"] is True
    assert recovered["reason"] == "available"
    assert recovered["cooldown"] == {}


def test_recent_capacity_failure_keeps_the_longer_cooldown():
    exhausted = {
        "recorded_at": 1000,
        "status": "request-failed",
        "ok": False,
        "model": MODEL,
        "reason": "local_capacity_exhausted",
    }

    snapshot = _snapshot(
        _mesh(workers=[_worker("spark-150")]),
        route_outcomes=[exhausted],
        now=1050,
    )

    assert snapshot["available"] is False
    assert snapshot["reason"] == "recent_local_model_request_failed"
    assert snapshot["cooldown"]["cooldown_seconds"] == 900
    assert snapshot["cooldown"]["remaining_seconds"] == 850


def test_recent_capacity_unavailable_uses_the_short_recovery_cooldown():
    unavailable = {
        "recorded_at": 1000,
        "status": "request-failed",
        "ok": False,
        "model": MODEL,
        "reason": "local_capacity_unavailable",
    }

    snapshot = _snapshot(
        _mesh(workers=[_worker("spark-150")]),
        route_outcomes=[unavailable],
        now=1050,
    )

    assert snapshot["available"] is False
    assert snapshot["reason"] == "recent_local_model_request_failed"
    assert snapshot["cooldown"]["cooldown_seconds"] == 60
    assert snapshot["cooldown"]["remaining_seconds"] == 10
