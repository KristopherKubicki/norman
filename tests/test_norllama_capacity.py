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


def _snapshot(mesh):
    return capacity.build_capacity_snapshot(
        mesh,
        requested_model="norman-code",
        selected_model=MODEL,
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
    assert snapshot["cloud_fallback"] is False


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
        "cloud_fallback": False,
        "retryable": True,
    }
