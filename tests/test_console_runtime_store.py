from __future__ import annotations

import uuid

from app import crud
from app.schemas.user import UserCreate
from app.services.console_runtime import ConsoleJobContract, ConsoleJobStatus
from app.services.console_runtime.store import DbConsoleRuntimeStore
from app.services.norllama.specialist_lanes import specialist_cascade_template


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "runtime-store@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="runtime-store@example.com",
                username="runtime_store",
                password="pass123",
            ),
        )
    return user


def test_db_console_runtime_store_persists_jobs_and_events(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-store-{uuid.uuid4().hex}"

    job = store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(
            objective="Persist runtime events",
            done_when=["events replay after restart"],
        ),
    )
    event = store.append_event(
        db,
        user_id=user.id,
        job_id=job.job_id,
        event_type="model.completed",
        payload={
            "provider": "norllama",
            "model": "qwen3:8b",
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
        },
        summary="Norllama completed",
        artifacts=["receipt.json"],
    )

    loaded = store.get_job(db, user_id=user.id, job_id=job.job_id)
    events = store.events_after(db, user_id=user.id, job_id=job.job_id)
    snapshot = store.activity_snapshot(db, user_id=user.id, job_id=job.job_id)

    assert loaded.job_id == job_id
    assert loaded.artifacts == ["receipt.json"]
    assert [item.event_type for item in events] == [
        "job.created",
        "model.completed",
    ]
    assert events[1].sequence > events[0].sequence
    assert event.sequence == events[1].sequence
    assert snapshot["category_counts"] == {"job": 1, "model": 1}
    assert snapshot["latest_event"]["summary"] == "Norllama completed"


def test_db_console_runtime_store_retries_event_sequence_collision(db, monkeypatch):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-sequence-retry-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Retry sequence collisions"),
    )
    existing_sequence = store.events_after(db, user_id=user.id, job_id=job_id)[
        0
    ].sequence
    original_next_sequence = store._next_sequence
    calls = 0

    def stale_once(session):
        nonlocal calls
        calls += 1
        if calls == 1:
            return existing_sequence
        return original_next_sequence(session)

    monkeypatch.setattr(store, "_next_sequence", stale_once)

    event = store.append_event(
        db,
        user_id=user.id,
        job_id=job_id,
        event_type="policy.mode_selected",
        payload={"active_mode": "cloud_llm_offline"},
    )
    events = store.events_after(db, user_id=user.id, job_id=job_id)

    assert calls == 2
    assert event.sequence > existing_sequence
    assert [item.sequence for item in events] == [existing_sequence, event.sequence]
    assert events[-1].event_type == "policy.mode_selected"


def test_db_console_runtime_store_retries_lease_sequence_collision(db, monkeypatch):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-lease-retry-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Retry lease sequence collisions"),
    )
    existing_sequence = store.events_after(db, user_id=user.id, job_id=job_id)[
        0
    ].sequence
    original_next_sequence = store._next_sequence
    calls = 0

    def stale_once(session):
        nonlocal calls
        calls += 1
        if calls == 1:
            return existing_sequence
        return original_next_sequence(session)

    monkeypatch.setattr(store, "_next_sequence", stale_once)

    job = store.lease_job(
        db,
        user_id=user.id,
        job_id=job_id,
        worker_id="runtime-worker",
    )
    events = store.events_after(db, user_id=user.id, job_id=job_id)

    assert calls == 2
    assert job.status == ConsoleJobStatus.LEASED
    assert events[-1].event_type == "job.leased"
    assert events[-1].sequence > existing_sequence


def test_db_console_runtime_store_retries_start_sequence_collision(db, monkeypatch):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-start-retry-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Retry start sequence collisions"),
    )
    store.lease_job(
        db,
        user_id=user.id,
        job_id=job_id,
        worker_id="runtime-worker",
    )
    existing_sequence = store.events_after(db, user_id=user.id, job_id=job_id)[
        -1
    ].sequence
    original_next_sequence = store._next_sequence
    calls = 0

    def stale_once(session):
        nonlocal calls
        calls += 1
        if calls == 1:
            return existing_sequence
        return original_next_sequence(session)

    monkeypatch.setattr(store, "_next_sequence", stale_once)

    job = store.start_job(
        db,
        user_id=user.id,
        job_id=job_id,
    )
    events = store.events_after(db, user_id=user.id, job_id=job_id)

    assert calls == 2
    assert job.status == ConsoleJobStatus.RUNNING
    assert events[-1].event_type == "job.started"
    assert events[-1].sequence > existing_sequence


def test_db_console_runtime_store_summarizes_route_offload_evidence(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-route-summary-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Measure local TUI offload"),
    )

    store.record_route_decision(
        db,
        user_id=user.id,
        job_id=job_id,
        decision={
            "task_kind": "summarize",
            "selected_lane": "summarizer",
            "selected_provider": "norllama",
            "selected_runner": "norllama",
            "selected_model": "qwen3:8b",
            "selected_endpoint": "http://192.168.2.150:18151/v1",
            "attribution": {
                "worker_id": "spark-150",
                "routing_scope": "direct_worker",
                "selection_source": "configured_worker_endpoint",
                "exact_worker": True,
            },
            "local": True,
            "cloud_proxy": False,
            "egress_class": "lan",
            "allowed": True,
        },
    )
    store.record_route_decision(
        db,
        user_id=user.id,
        job_id=job_id,
        decision={
            "task_kind": "write",
            "selected_lane": "cloud-verifier",
            "selected_provider": "bedrock",
            "selected_runner": "bedrock",
            "selected_model": "claude-check",
            "local": False,
            "cloud_proxy": False,
            "egress_class": "cloud_llm",
            "allowed": True,
        },
    )
    specialist_cascade = specialist_cascade_template(
        phase="summarize",
        selected_provider="norllama",
        selected_model="qwen3:8b",
        selected_worker="spark-150",
    )
    specialist_cascade["lanes"][0]["status"] = "pass"
    specialist_cascade["deterministic_experts"][0]["status"] = "pass"
    store.append_event(
        db,
        user_id=user.id,
        job_id=job_id,
        event_type="model.completed",
        payload={
            "provider": "norllama",
            "model": "qwen3:8b",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "route_receipt": {
                "schema": "norman.norllama.route-receipt.v1",
                "phase": "summarize",
                "selected_provider": "norllama",
                "selected_model": "qwen3:8b",
                "selected_worker": "spark-150",
                "usage_bucket": "offline_local",
                "cloud_proxy": False,
                "specialist_cascade": specialist_cascade,
            },
        },
    )
    store.record_planner_receipt(
        db,
        user_id=user.id,
        job_id=job_id,
        receipt={
            "task_kind": "scout",
            "status": "planned",
            "provider": "norllama",
            "route": {
                "provider": "norllama",
                "capability": "scout",
                "attribution": {
                    "worker_id": "spark-150",
                    "routing_scope": "direct_worker",
                    "selection_source": "gateway_response",
                },
            },
        },
    )

    snapshot = store.activity_snapshot(db, user_id=user.id, job_id=job_id)
    summary = snapshot["route_summary"]
    direct = store.route_activity_summary(db, user_id=user.id, job_id=job_id)

    assert summary["schema"] == "norman.console-runtime.route-summary.v1"
    assert summary["route"]["total"] == 2
    assert summary["route"]["offline_safe"] == 1
    assert summary["route"]["cloud_llm"] == 1
    assert summary["route"]["spark_hint"] == 1
    assert summary["route"]["by_provider"] == {"norllama": 1, "bedrock": 1}
    assert summary["route"]["by_worker"] == {"spark-150": 1}
    assert summary["model"]["completed"] == 1
    assert summary["model"]["local"] == 1
    assert summary["model"]["tokens"] == 15
    assert summary["usage_ledger"]["schema"] == (
        "norman.console-runtime.usage-ledger.v1"
    )
    assert summary["usage_ledger"]["total_tokens"] == 15
    assert summary["usage_ledger"]["offline_tokens"] == 15
    assert summary["usage_ledger"]["cloud_tokens"] == 0
    assert summary["usage_ledger"]["cloud_llm_tokens"] == 0
    assert summary["usage_ledger"]["by_provider"] == {"norllama": 15}
    assert summary["local_first_kpi"]["schema"] == (
        "norman.console-runtime.local-first-kpi.v1"
    )
    assert summary["local_first_kpi"]["status"] == "on_target"
    assert summary["local_first_kpi"]["offline_token_percent"] == 100.0
    assert summary["planner"]["receipts"] == 1
    assert summary["planner"]["local"] == 1
    assert summary["planner"]["spark_hint"] == 1
    assert summary["planner"]["by_worker"] == {"spark-150": 1}
    assert summary["workers"]["by_id"] == {"spark-150": 2}
    assert summary["local_evidence_count"] == 3
    assert summary["cloud_evidence_count"] == 1
    assert summary["spark_evidence_count"] == 2
    assert direct == {**summary, "job_id": job_id}
    proof = store.local_first_proof(db, user_id=user.id, session_limit=20)
    assert proof["schema"] == "norman.console-runtime.local-first-proof.v1"
    assert proof["totals"]["local_tokens"] >= 15
    assert proof["totals"]["spark_evidence_count"] >= 2
    assert proof["totals"]["specialist_required_count"] >= 21
    assert proof["totals"]["specialist_evidence_count"] >= 2
    assert proof["release_gate"]["proves_local_first"] is True
    assert proof["release_gate"]["has_spark_evidence"] is True
    assert proof["release_gate"]["specialist_cascade_visible"] is True
    assert proof["release_gate"]["has_specialist_evidence"] is True
    assert proof["sessions"][0]["specialist_lanes"]["receipt_auditor"] == 1
    assert proof["sessions"][0]["deterministic_experts"]["codeql"] == 1
    assert proof["sessions"][0]["models_by_phase"]


def test_db_console_runtime_store_breaks_out_usage_ledger_by_provider(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-usage-ledger-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Measure provider token split"),
    )

    events = [
        (
            "norllama",
            "qwen3.6:27b",
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            {"egress_class": "lan", "local": True, "metadata": {"session_name": "A"}},
        ),
        (
            "bedrock",
            "claude-check",
            {"input_tokens": 70, "output_tokens": 30, "total_tokens": 100},
            {"egress_class": "cloud_llm", "metadata": {"session_name": "A"}},
        ),
        (
            "openai",
            "gpt-5-mini",
            {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            {"egress_class": "cloud_llm", "metadata": {"session_name": "B"}},
        ),
        (
            "perplexity",
            "sonar",
            {"input_tokens": 25, "output_tokens": 15, "total_tokens": 40},
            {"egress_class": "web_research", "metadata": {"session_name": "B"}},
        ),
    ]
    for provider, model, usage, extra in events:
        store.append_event(
            db,
            user_id=user.id,
            job_id=job_id,
            event_type="model.completed",
            payload={
                "provider": provider,
                "model": model,
                "usage": usage,
                **extra,
            },
        )

    summary = store.route_activity_summary(db, user_id=user.id, job_id=job_id)
    ledger = summary["usage_ledger"]

    assert ledger["total_tokens"] == 185
    assert ledger["offline_tokens"] == 15
    assert ledger["cloud_tokens"] == 170
    assert ledger["cloud_llm_tokens"] == 130
    assert ledger["cloud_amazon_tokens"] == 100
    assert ledger["cloud_openai_tokens"] == 30
    assert ledger["perplexity_tokens"] == 40
    assert ledger["third_party_tokens"] == 40
    assert ledger["by_provider"] == {
        "bedrock": 100,
        "norllama": 15,
        "openai": 30,
        "perplexity": 40,
    }
    assert ledger["by_scope"]["A"]["total_tokens"] == 115
    assert ledger["by_scope"]["B"]["cloud_tokens"] == 70
    assert ledger["by_job"][job_id]["total_tokens"] == 185
    assert sum(row["total_tokens"] for row in ledger["by_day"].values()) == 185
    assert summary["local_first_kpi"]["status"] == "cloud_heavy"
    assert summary["local_first_kpi"]["cloud_llm_tokens"] == 130
    assert summary["local_first_kpi"]["perplexity_tokens"] == 40


def test_db_console_runtime_store_dedupes_kernel_primary_visible_echo(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-kernel-ledger-dedupe-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Count kernel local usage once"),
    )

    store.append_event(
        db,
        user_id=user.id,
        job_id=job_id,
        event_type="model.completed",
        payload={
            "provider": "norllama",
            "model": "gemma3:1b",
            "usage": {"input_tokens": 73, "output_tokens": 4, "total_tokens": 77},
            "route_receipt": {
                "selected_provider": "norllama",
                "selected_model": "gemma3:1b",
                "selected_worker": "mac-mini-133",
                "usage_bucket": "offline_local",
                "cloud_proxy": False,
            },
        },
    )
    store.append_event(
        db,
        user_id=user.id,
        job_id=job_id,
        event_type="model.completed",
        payload={
            "provider": "localllm",
            "model": "gemma3:1b",
            "usage": {
                "total_tokens": 77,
                "route_execution": "console_runtime_kernel",
                "kernel_primary": True,
                "kernel_local_tokens": 77,
                "kernel_cloud_tokens": 0,
            },
        },
        summary="Visible wrapper echoed the kernel result.",
    )

    summary = store.route_activity_summary(db, user_id=user.id, job_id=job_id)
    ledger = summary["usage_ledger"]

    assert summary["model"]["completed"] == 1
    assert summary["model"]["tokens"] == 77
    assert summary["model"]["by_provider"] == {"norllama": 1}
    assert ledger["total_tokens"] == 77
    assert ledger["offline_tokens"] == 77
    assert ledger["by_provider"] == {"norllama": 77}
    assert ledger["by_model"] == {"gemma3:1b": 77}


def test_db_console_runtime_store_excludes_tui_stream_jobs_from_runnable(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    stream_id = f"job-tui-stream-{uuid.uuid4().hex}"
    shadow_id = f"job-tui-shadow-{uuid.uuid4().hex}"
    promoted_id = f"job-tui-promoted-{uuid.uuid4().hex}"
    work_id = f"job-runnable-{uuid.uuid4().hex}"

    store.create_job(
        db,
        user_id=user.id,
        job_id=stream_id,
        contract=ConsoleJobContract(
            objective="Live TUI runtime stream for NetOps",
            question_budget=0,
            authority_flags={"source": "agent_console_web"},
            route_policy={
                "runtime": "shell",
                "planner": "norllama",
                "model_proxy": "norllama",
            },
            metadata={"source": "agent_console_web"},
        ),
        metadata={"source": "agent_console_web"},
    )
    store.create_job(
        db,
        user_id=user.id,
        job_id=shadow_id,
        contract=ConsoleJobContract(
            objective="Shadow a TUI turn without executing it",
            question_budget=0,
            authority_flags={
                "source": "agent_console_web",
                "kind": "tui_turn_shadow",
            },
            route_policy={
                "provider": "norllama",
                "planner": "norllama",
                "model_proxy": "norllama",
                "turn_shadow": True,
                "continuous_goal_candidate": True,
            },
            metadata={
                "source": "agent_console_web",
                "kind": "tui_turn_shadow",
                "kernel_execution_enabled": False,
                "continuous_goal_candidate": True,
            },
        ),
        metadata={
            "source": "agent_console_web",
            "kind": "tui_turn_shadow",
            "kernel_execution_enabled": False,
        },
    )
    store.create_job(
        db,
        user_id=user.id,
        job_id=promoted_id,
        contract=ConsoleJobContract(
            objective="Execute a safe local-first TUI turn through the kernel",
            question_budget=0,
            authority_flags={
                "source": "agent_console_web",
                "kind": "tui_turn_shadow",
                "kernel_execution_enabled": True,
                "kernel_execution_candidate": True,
            },
            route_policy={
                "provider": "norllama",
                "planner": "norllama",
                "model_proxy": "norllama",
                "turn_shadow": True,
                "kernel_execution_enabled": True,
                "kernel_execution_candidate": True,
                "continuous_goal_candidate": True,
            },
            metadata={
                "source": "agent_console_web",
                "kind": "tui_turn_shadow",
                "kernel_execution_enabled": True,
                "kernel_execution_candidate": True,
                "continuous_goal_candidate": True,
            },
        ),
        metadata={
            "source": "agent_console_web",
            "kind": "tui_turn_shadow",
            "kernel_execution_enabled": True,
            "kernel_execution_candidate": True,
            "continuous_goal_candidate": True,
        },
    )
    store.create_job(
        db,
        user_id=user.id,
        job_id=work_id,
        contract=ConsoleJobContract(objective="Run real runtime work"),
    )

    runnable = store.list_runnable_jobs(db, limit=100)
    runnable_ids = [job.job_id for _, job in runnable]

    assert stream_id not in runnable_ids
    assert shadow_id not in runnable_ids
    assert promoted_id in runnable_ids
    assert work_id in runnable_ids


def test_db_console_runtime_store_records_planner_receipts(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-planner-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Plan runtime handoff"),
    )

    event = store.record_planner_receipt(
        db,
        user_id=user.id,
        job_id=job_id,
        receipt={
            "task_kind": "filter",
            "status": "planned",
            "route": {"provider": "norllama", "capability": "filter"},
            "evidence_paths": ["filter-receipt.json"],
        },
        capabilities={"provider": "norllama", "models": ["filter-local"]},
    )
    loaded = store.get_job(db, user_id=user.id, job_id=job_id)
    snapshot = store.activity_snapshot(db, user_id=user.id, job_id=job_id)

    assert event.event_type == "planner.receipt"
    assert event.category == "planner"
    assert event.payload["route"]["capability"] == "filter"
    assert loaded.artifacts == ["filter-receipt.json"]
    assert snapshot["category_counts"] == {"job": 1, "planner": 1}


def test_db_console_runtime_store_mutates_job_lifecycle(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-lifecycle-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Run one runtime step"),
    )

    leased = store.lease_job(
        db, user_id=user.id, job_id=job_id, worker_id="worker-a", lease_seconds=30
    )
    started = store.start_job(db, user_id=user.id, job_id=job_id)
    completed = store.complete_job(
        db,
        user_id=user.id,
        job_id=job_id,
        summary="Runtime step finished.",
    )
    events = store.events_after(db, user_id=user.id, job_id=job_id)

    assert leased.status == "leased"
    assert leased.lease is not None
    assert leased.lease.worker_id == "worker-a"
    assert started.status == "running"
    assert completed.status == "done"
    assert [event.event_type for event in events] == [
        "job.created",
        "job.leased",
        "job.started",
        "job.completed",
    ]


def test_db_console_runtime_store_approves_waiting_job_for_resume(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-approval-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Resume after operator approval"),
    )
    store.lease_job(
        db, user_id=user.id, job_id=job_id, worker_id="worker-a", lease_seconds=30
    )
    store.start_job(db, user_id=user.id, job_id=job_id)
    held = store.require_approval(
        db,
        user_id=user.id,
        job_id=job_id,
        reason="live execution requires approval",
        requested_by="worker-a",
    )

    approved = store.approve_job(
        db,
        user_id=user.id,
        job_id=job_id,
        reason="operator approved one live step",
        approved_by="operator@example.com",
    )
    events = store.events_after(db, user_id=user.id, job_id=job_id)

    assert held.status == "waiting_approval"
    assert approved.status == "checkpointed"
    assert approved.lease is None
    assert events[-1].event_type == "approval.approved"
    assert events[-1].category == "approval"
    assert events[-1].payload["approved_by"] == "operator@example.com"


def test_db_console_runtime_store_rejects_waiting_job_approval(db):
    user = _ensure_user(db)
    store = DbConsoleRuntimeStore()
    job_id = f"job-approval-reject-{uuid.uuid4().hex}"
    store.create_job(
        db,
        user_id=user.id,
        job_id=job_id,
        contract=ConsoleJobContract(objective="Reject unsafe live execution"),
    )
    store.require_approval(
        db,
        user_id=user.id,
        job_id=job_id,
        reason="live execution requires approval",
        requested_by="worker-a",
    )

    rejected = store.reject_approval(
        db,
        user_id=user.id,
        job_id=job_id,
        reason="not safe yet",
        rejected_by="operator@example.com",
    )
    events = store.events_after(db, user_id=user.id, job_id=job_id)

    assert rejected.status == "blocked"
    assert rejected.last_error == "not safe yet"
    assert events[-1].event_type == "approval.rejected"
    assert events[-1].payload["rejected_by"] == "operator@example.com"
