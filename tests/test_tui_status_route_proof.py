from scripts import tui_status_route_proof as proof


def _probe(
    *,
    local_healthy: bool = True,
    planner_ready: bool | None = True,
    deterministic: bool = False,
    success: bool = True,
    runtime: str | None = None,
    model: str | None = None,
) -> dict:
    runtime = runtime or ("localllm" if deterministic else "codex")
    model = model or (
        "deterministic-status" if deterministic else "openai.gpt-5.6-terra"
    )
    before = {
        "local_llm_health": {"ok": local_healthy},
        "codexspark": {
            "execution": "access-check",
            "can_execute": False,
        },
    }
    if planner_ready is not None:
        before["local_planner_readiness"] = {
            "configured": True,
            "ready": planner_ready,
            "status": "ready" if planner_ready else "unavailable",
        }
    return {
        "ok": True,
        "skipped": False,
        "ask_http_status": 200 if deterministic else 202,
        "ask": {
            "accepted": True,
            "receipt_reason": "deterministic_status" if deterministic else "",
        },
        "before": before,
        "final": {
            "last_prompt_contains_nonce": True,
            "pending": False,
            "last_error": "",
        },
        "last_turn": {
            "success": success,
            "runtime": runtime,
            "model": model,
            "route_verifier": "local-planner-verifier",
            "fallback_reason": "",
            "started_at": 1_700_000_000,
            "finished_at": 1_700_000_002,
            "estimated_cost_usd": 0.012345,
            "total_tokens": 40 if not deterministic else 0,
            "local_preflight_used": bool(planner_ready) and not deterministic,
            "local_preflight_status": (
                "ok" if planner_ready and not deterministic else ""
            ),
            "local_preflight_model": "qwen3.6:35b-a3b-q4_K_M",
            "local_preflight_tokens": (
                18 if planner_ready and not deterministic else 0
            ),
            "local_preflight_candidate_lane": "planner",
        },
    }


def test_proof_form_uses_unlocked_status_only_codex_route() -> None:
    form = proof.proof_form("abc123")

    assert form["runtime"] == "codex"
    assert form["route_lock"] == "0"
    assert form["job_budget"] == "quick"
    assert "abc123" in form["message"]
    assert "No tools or changes." in form["message"]


def test_remote_command_uses_execution_host_locality(monkeypatch) -> None:
    host = proof.sync.DiscoveryHost(
        name="norman",
        ssh_target="192.0.2.10",
        use_sudo=True,
        env_globs=(),
        public_host="norman.example.invalid",
        lan_host="192.0.2.10",
    )
    monkeypatch.setattr(proof.sync, "host_runs_local", lambda _: True)

    assert proof.remote_command(host) == ["sudo", "python3", "-"]


def test_live_probe_reads_last_turn_from_status_snapshot() -> None:
    assert 'fetch_json("/api/usage?recent=1"' not in proof.REMOTE_STATUS_ROUTE_PROOF
    assert 'compact_last_turn(\n        {"usage": as_dict(snapshot).get("usage")}' in (
        proof.REMOTE_STATUS_ROUTE_PROOF
    )
    assert 'planner_readiness = as_dict(source.get("local_planner_readiness"))' in (
        proof.REMOTE_STATUS_ROUTE_PROOF
    )


def test_cold_recovery_drill_uses_isolated_state_without_inference() -> None:
    assert (
        'NORMAN_CODEX_WEB_STATE_DIR"] = state_dir' in proof.REMOTE_COLD_RECOVERY_DRILL
    )
    assert "planner-preflight" in proof.REMOTE_COLD_RECOVERY_DRILL
    assert "local_llm_generate_once" not in proof.REMOTE_COLD_RECOVERY_DRILL

    row = proof.validate_cold_recovery_drill(
        {
            "ok": True,
            "inference_attempted": False,
            "state_dir_isolated": True,
            "fresh_cooldown_seconds": 60,
            "fresh_cooldown_active": True,
            "stale_cooldown_cleared": True,
        }
    )

    assert row["passed"] is True
    assert row["outcome"] == "cold_recovery_verified"


def test_cold_recovery_drill_rejects_stale_timeout_that_still_blocks_recovery() -> None:
    row = proof.validate_cold_recovery_drill(
        {
            "ok": False,
            "inference_attempted": False,
            "state_dir_isolated": True,
            "fresh_cooldown_seconds": 900,
            "fresh_cooldown_active": True,
            "stale_cooldown_cleared": False,
        }
    )

    assert row["passed"] is False
    assert "planner cold-load cooldown exceeded 60 seconds" in row["failures"]
    assert "stale planner timeout still blocked local recovery" in row["failures"]


def test_ready_local_planner_status_requires_norllama_preflight() -> None:
    row = proof.validate_proof(_probe())

    assert row["passed"] is True
    assert row["outcome"] == "norllama_preflight_cloud_authority"
    assert row["preflight"]["model"] == "qwen3.6:35b-a3b-q4_K_M"
    assert row["final_authority"] == "codex/openai.gpt-5.6-terra"


def test_recorded_preflight_is_authoritative_when_health_metadata_is_omitted() -> None:
    probe = _probe(local_healthy=False, planner_ready=None)
    probe["last_turn"].update(
        {
            "local_preflight_used": True,
            "local_preflight_status": "ok",
            "local_preflight_model": "qwen3.6:35b-a3b-q4_K_M",
            "local_preflight_tokens": 18,
            "local_preflight_candidate_lane": "planner",
        }
    )

    row = proof.validate_proof(probe)

    assert row["passed"] is True
    assert row["outcome"] == "norllama_preflight_cloud_authority"


def test_ready_local_planner_accepts_deterministic_state_read() -> None:
    row = proof.validate_proof(_probe(deterministic=True))

    assert row["passed"] is True
    assert row["outcome"] == "deterministic_status"
    assert row["deterministic_state_read"] is True
    assert row["local_healthy_before"] is False
    assert row["preflight"]["used"] is False
    assert row["preflight"]["tokens"] == 0


def test_generic_local_health_does_not_block_deterministic_state_read() -> None:
    row = proof.validate_proof(
        _probe(
            local_healthy=True,
            planner_ready=False,
            deterministic=True,
            runtime="localllm",
            model="deterministic-status",
        )
    )

    assert row["passed"] is True
    assert row["outcome"] == "deterministic_status"


def test_unavailable_local_status_accepts_deterministic_state_read() -> None:
    row = proof.validate_proof(
        _probe(
            local_healthy=False,
            planner_ready=False,
            deterministic=True,
            runtime="localllm",
            model="deterministic-status",
        )
    )

    assert row["passed"] is True
    assert row["outcome"] == "deterministic_status"


def test_proof_rejects_named_codexspark_as_live_final_runtime() -> None:
    row = proof.validate_proof(
        _probe(runtime="codexspark", model="gpt-5.3-codex-spark")
    )

    assert row["passed"] is False
    assert (
        "named codexspark preview was selected as a live final runtime"
        in row["failures"]
    )


def test_proof_rejects_non_terra_cloud_authority() -> None:
    row = proof.validate_proof(_probe(model="openai.gpt-5.5"))

    assert row["passed"] is False
    assert "cloud final authority did not use GPT-5.6 Terra" in row["failures"]


def test_summary_tracks_preflight_and_named_preview_contract() -> None:
    rows = [
        proof.validate_proof(_probe()),
        proof.validate_proof(
            _probe(
                local_healthy=False,
                planner_ready=False,
                deterministic=True,
                runtime="localllm",
                model="deterministic-status",
            )
        ),
    ]

    summary = proof.build_summary(rows)

    assert summary["targets"] == 2
    assert summary["passed"] == 2
    assert summary["successful_norllama_preflights"] == 1
    assert summary["deterministic_state_reads"] == 1
    assert summary["named_codexspark_access_check_contract_ok"] is True
    assert summary["route_scorecard"]["observed_turns"] == 2
    assert summary["route_scorecard"]["cloud_final_authority_turns"] == 1
    assert summary["route_scorecard"]["verifier_recorded_turns"] == 2
    assert summary["route_scorecard"]["fallback_turns"] == 0
    assert summary["route_scorecard"]["total_latency_ms"] == 4000
    assert summary["route_scorecard"]["estimated_cost_usd"] == 0.02469


def test_markdown_includes_compact_route_scorecard_columns() -> None:
    row = proof.validate_proof(_probe())
    row["requested_route"] = {
        "runtime": "codex",
        "model": "",
        "service_tier": "default",
    }
    report = {
        "run_id": "scorecard",
        "generated_at": 1_700_000_000,
        "summary": proof.build_summary([row]),
        "results": [row],
    }

    markdown = proof.render_markdown(report)

    assert "Route scorecard:" in markdown
    assert "Requested route" in markdown
    assert "Verifier/fallback" in markdown
    assert "codex/auto/default" in markdown
    assert "$0.012345" in markdown


def test_select_instances_records_missing_requested_host(monkeypatch) -> None:
    instance = proof.sync.ConsoleInstance(
        name="uplink",
        host_name="networking-host",
        ssh_target="debian@example.invalid",
        use_sudo=True,
        env_file="/etc/uplink/codex-web.env",
        web_path="/opt/uplink/web.py",
        launch_path="/opt/uplink/launch.sh",
        supervisor_path="/opt/uplink/supervisor.sh",
        restart_units=(),
        agent_label="Uplink",
        web_port="8765",
        web_token="token",
        prompt_file="/opt/uplink/prompt.txt",
        codex_home="/home/uplink/.codex",
    )
    monkeypatch.setattr(
        proof.sync,
        "discover_all_instances",
        lambda host_filter: (
            {"norman": [], "networking-host": [instance]},
            {"uplink": instance},
        ),
    )
    monkeypatch.setattr(
        proof.sync,
        "requested_host_filter",
        lambda targets: ["norman", "networking-host"],
    )
    monkeypatch.setattr(
        proof.sync,
        "select_instances",
        lambda targets, discovered_by_host, discovered_by_name: {
            "networking-host": [instance]
        },
    )

    instances, failures = proof.select_instances(["norman", "networking-host"])

    assert instances == [instance]
    assert len(failures) == 1
    assert failures[0]["target"] == "norman"
    assert failures[0]["outcome"] == "discovery_failed"
