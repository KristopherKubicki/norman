from __future__ import annotations

import importlib.util
import os
import sys
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_child_agents():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "agent_console_child_agents.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_console_child_agents_test",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_web_renderer(web_source: str):
    root = Path(__file__).resolve().parents[1]
    script_path = root / web_source
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location(
        f"{script_path.stem}_{abs(hash(web_source))}",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runtime_request(calls: list[tuple[str, str, dict[str, object] | None, float]]):
    def request(
        method: str,
        path: str,
        payload: dict[str, object] | None,
        timeout: float,
    ) -> dict[str, object]:
        calls.append((method, path, payload, timeout))
        if path == "/console-runtime/jobs":
            return {"job_id": str(payload["job_id"])}
        if path == "/console-runtime/workstreams":
            return {"workstream_id": str(payload["workstream_id"])}
        if path.endswith("/subtasks"):
            subtasks = payload["subtasks"]
            assert isinstance(subtasks, list)
            return {"items": [{"job_id": str(subtasks[0]["job_id"])}]}
        return {}

    return request


def _broker(module, tmp_path: Path, *, calls=None):
    parent_home = tmp_path / "parent-codex-home"
    parent_home.mkdir()
    worker_script = tmp_path / "agent_console_web.py"
    worker_script.write_text("# child worker placeholder\n", encoding="utf-8")
    runtime_calls = calls if calls is not None else []
    return module.ChildAgentBroker(
        state_dir=tmp_path / "state",
        parent_session="parent",
        parent_tmux_socket="parent-socket",
        parent_script_path=tmp_path / "parent_web.py",
        worker_script_path=worker_script,
        codex_home=parent_home,
        token="test-token",
        agent_name="Parent",
        workdir=tmp_path / "worktree",
        runtime_enabled=True,
        runtime_request=_runtime_request(runtime_calls),
    )


def _record(
    broker,
    *,
    child_id: str,
    status: str = "completed",
    label: str = "Child agent",
    objective: str = "Inspect the change.",
    write_mode: str = "read_only",
    pid: int = 0,
    updated_at: int = 1,
) -> dict[str, object]:
    state_dir = broker.children_dir / child_id
    return {
        "id": child_id,
        "label": label,
        "objective": objective,
        "write_mode": write_mode,
        "status": status,
        "created_at": updated_at,
        "updated_at": updated_at,
        "pid": pid,
        "pgid": pid,
        "port": 0,
        "url": "",
        "state_dir": str(state_dir),
        "codex_home": str(state_dir / "codex-home"),
        "session": f"parent-child-{child_id}",
        "tmux_socket": f"parent-socket-child-{child_id}",
        "runtime_job_id": f"{child_id}-runtime",
        "workstream_id": f"{child_id}-workstream",
        "result": "",
        "artifacts": [],
        "error": "",
        "retry_count": 0,
        "runtime_result_recorded_at": 0,
        "retry_of": "",
    }


def _seed(broker, record: dict[str, object]) -> None:
    with broker._locked_registry() as registry:
        registry["children"].append(record)


def _prepare_successful_spawn(monkeypatch, broker) -> list[dict[str, object]]:
    submitted: list[dict[str, object]] = []
    monkeypatch.setattr(broker, "_allocate_port", lambda: 43123)
    monkeypatch.setattr(
        broker,
        "_start_child_process",
        lambda record, port: SimpleNamespace(pid=845321),
    )
    monkeypatch.setattr(broker, "_wait_for_child_health", lambda child_url: None)
    monkeypatch.setattr(
        broker,
        "_submit_child_objective",
        lambda child_url, record: submitted.append(dict(record)),
    )
    return submitted


def _write_skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")
    return skill


def test_child_agent_rejects_nested_launches(monkeypatch, tmp_path: Path) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    monkeypatch.setenv("NORMAN_CHILD_AGENT", "1")

    with pytest.raises(module.ChildAgentConflict, match="cannot launch nested"):
        broker.spawn(label="Nested", objective="Do not run.")


def test_provisioning_children_reserve_all_ten_launch_slots(tmp_path: Path) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    now = module._now()
    for index in range(module.MAX_ACTIVE_CHILDREN):
        _seed(
            broker,
            _record(
                broker,
                child_id=f"child-{index}",
                status="provisioning",
                updated_at=now,
            ),
        )

    with pytest.raises(module.ChildAgentConflict, match="At most 10"):
        broker.spawn(label="Overflow", objective="This must not be admitted.")


def test_child_runtime_delegation_uses_empty_pool_neutral_policies(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_child_agents()
    calls: list[tuple[str, str, dict[str, object] | None, float]] = []
    broker = _broker(module, tmp_path, calls=calls)
    _prepare_successful_spawn(monkeypatch, broker)

    child = broker.spawn(
        label="Review",
        objective="Review the implementation and return findings.",
    )

    assert child["status"] == "running"
    assert [path for _, path, _, _ in calls] == [
        "/console-runtime/jobs",
        "/console-runtime/workstreams",
        f"/console-runtime/workstreams/{child['id']}-workstream/subtasks",
    ]
    coordinator_payload = calls[0][2]
    workstream_payload = calls[1][2]
    delegated_payload = calls[2][2]
    assert coordinator_payload["route_policy"] == {}
    assert coordinator_payload["question_budget"] == 0
    assert workstream_payload["max_concurrency"] == module.MAX_ACTIVE_CHILDREN
    subtask = delegated_payload["subtasks"][0]
    assert subtask["route_policy"] == {}
    assert subtask["question_budget"] == 0
    assert "model" not in subtask
    assert "spark" not in str(delegated_payload).lower()


def test_child_objective_locks_to_localllm_pool(tmp_path: Path, monkeypatch) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    captured: list[tuple[str, str, dict[str, object], bool]] = []
    record = _record(
        broker,
        child_id="child-pool",
        status="running",
        objective="Check the pool route.",
        write_mode="read_only",
    )

    def capture(method, url, payload=None, *, raw=False):
        captured.append((method, url, payload, raw))
        return {}

    monkeypatch.setattr(broker, "_child_json_request", capture)
    broker._submit_child_objective("http://127.0.0.1:43123", record)

    assert len(captured) == 1
    method, url, payload, raw = captured[0]
    assert method == "POST"
    assert url.endswith("/api/ask")
    assert raw is False
    assert set(payload) == {"runtime", "route_lock", "message"}
    assert payload["runtime"] == "localllm"
    assert payload["route_lock"] is True
    assert "Inspect and analyze only" in payload["message"]
    assert "spark" not in str(payload).lower()


def test_child_process_uses_an_isolated_codex_home(monkeypatch, tmp_path: Path) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    broker.workdir.mkdir()
    (broker.codex_home / "auth.json").write_text("parent state", encoding="utf-8")
    record = _record(broker, child_id="child-isolated", status="starting")
    broker._prepare_child_dirs(record)
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(pid=845322)

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    process = broker._start_child_process(record, 43124)

    assert process.pid == 845322
    child_home = Path(record["codex_home"])
    assert child_home != broker.codex_home
    assert list(child_home.iterdir()) == []
    env = captured["env"]
    assert env["CODEX_HOME"] == str(child_home)
    assert env["NORMAN_CODEX_HOME"] == str(child_home)
    assert env["NORMAN_CODEX_DEFAULT_RUNTIME"] == "localllm"
    assert env["NORMAN_CODEX_FORCE_DEFAULT_RUNTIME"] == "1"
    assert env["NORMAN_CONSOLE_RUNTIME_ENABLED"] == "0"
    assert env["NORMAN_CHILD_AGENT"] == "1"
    assert env["NORMAN_CHILD_DEPTH"] == "1"


@pytest.mark.parametrize("scope", ("work", "personal"))
def test_child_inherits_only_parent_scoped_skill_links(
    monkeypatch, tmp_path: Path, scope: str
) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    work_root = tmp_path / "work-skills"
    personal_root = tmp_path / "personal-skills"
    scoped_skill = _write_skill(
        work_root if scope == "work" else personal_root,
        f"{scope}-only",
    )
    generic_skill = _write_skill(tmp_path / "generic-skills", "generic")
    monkeypatch.setattr(
        module,
        "SCOPED_SKILL_SOURCE_ROOTS",
        (work_root, personal_root),
    )
    parent_skills = broker.codex_home / "skills"
    parent_skills.mkdir()
    (parent_skills / scoped_skill.name).symlink_to(
        scoped_skill,
        target_is_directory=True,
    )
    (parent_skills / generic_skill.name).symlink_to(
        generic_skill,
        target_is_directory=True,
    )
    record = _record(broker, child_id=f"child-{scope}", status="starting")

    broker._prepare_child_dirs(record)

    child_skills = Path(record["codex_home"]) / "skills"
    inherited = child_skills / scoped_skill.name
    assert inherited.is_symlink()
    assert inherited.resolve() == scoped_skill
    assert not (child_skills / generic_skill.name).exists()


def test_rename_persists_in_the_child_registry(tmp_path: Path) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    _seed(broker, _record(broker, child_id="child-rename", label="Initial"))

    renamed = broker.rename("child-rename", "Security audit")

    assert renamed["label"] == "Security audit"
    assert broker.list_children()[0]["label"] == "Security audit"


def test_artifacts_are_bounded_to_child_or_worktree_paths(tmp_path: Path) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    broker.workdir.mkdir()
    record = _record(broker, child_id="child-artifacts", status="completed")
    state_dir = Path(record["state_dir"])
    state_dir.mkdir(parents=True)
    valid = []
    for index in range(module.MAX_ARTIFACTS + 2):
        path = broker.workdir / f"artifact-{index}.txt"
        path.write_text("ok", encoding="utf-8")
        valid.append(str(path))
    inside_state = state_dir / "result.txt"
    inside_state.write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")

    artifacts = broker._safe_artifacts(
        record, valid + [str(inside_state), str(outside)]
    )

    assert len(artifacts) == module.MAX_ARTIFACTS
    assert str(outside.resolve()) not in artifacts
    assert all(str(broker.workdir.resolve()) in item for item in artifacts)


def test_cancel_cancels_the_runtime_job_before_terminating_child(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    _seed(
        broker,
        _record(broker, child_id="child-cancel", status="running", pid=os.getpid()),
    )
    events: list[str] = []
    monkeypatch.setattr(
        broker,
        "_cancel_runtime_job",
        lambda record, *, reason: events.append("runtime"),
    )
    monkeypatch.setattr(
        broker,
        "_terminate_child_process",
        lambda record: events.append("process"),
    )

    cancelled = broker.cancel("child-cancel")

    assert events == ["runtime", "process"]
    assert cancelled["status"] == "cancelled"


def test_retry_creates_a_fresh_isolated_child(monkeypatch, tmp_path: Path) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    original = _record(
        broker,
        child_id="child-original",
        label="Regression review",
        objective="Inspect the regression and report findings.",
    )
    _seed(broker, original)
    _prepare_successful_spawn(monkeypatch, broker)

    replacement = broker.retry("child-original")

    assert replacement["retry_of"] == "child-original"
    assert replacement["retry_count"] == 1
    assert replacement["id"] != "child-original"
    assert replacement["state_dir"] != original["state_dir"]
    assert replacement["codex_home"] != original["codex_home"]
    assert replacement["session"] != original["session"]
    assert Path(replacement["state_dir"]).is_dir()
    assert Path(replacement["codex_home"]).is_dir()


def test_reconciliation_stops_dead_processes_and_expires_stale_launches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_child_agents()
    broker = _broker(module, tmp_path)
    now = module._now()
    _seed(
        broker,
        _record(
            broker,
            child_id="child-dead",
            status="running",
            pid=845323,
            updated_at=now,
        ),
    )
    _seed(
        broker,
        _record(
            broker,
            child_id="child-stale-launch",
            status="provisioning",
            updated_at=now - module.CHILD_STARTUP_GRACE_SECONDS,
        ),
    )
    monkeypatch.setattr(module, "_is_pid_alive", lambda pid: False)

    children = {child["id"]: child for child in broker.list_children()}

    assert children["child-dead"]["status"] == "stopped"
    assert children["child-dead"]["error"] == "Child web process exited."
    assert children["child-stale-launch"]["status"] == "failed"
    assert "did not attach" in children["child-stale-launch"]["error"]


@pytest.mark.parametrize(
    "web_source",
    (
        "scripts/agent_console_template/agent_console_web.py",
        "scripts/norman_codex_web.py",
    ),
)
def test_child_agent_ui_uses_compact_contextual_actions_and_inline_rename(
    web_source: str,
) -> None:
    source = (Path(__file__).resolve().parents[1] / web_source).read_text(
        encoding="utf-8"
    )

    assert ".child-agent-action[data-icon]::before" in source
    assert "container-type: inline-size;" in source
    assert "@container (max-width: 420px)" in source
    assert 'id="child-agents-capacity"' in source
    assert 'id="child-agents-capacity-fill"' in source
    assert "button.dataset.action = action;" in source
    assert 'className = "ghost utility-button child-agent-action"' in source
    assert 'button.setAttribute("aria-label", label);' in source
    assert 'editingId: ""' in source
    assert 'editingLabel: ""' in source
    assert "function childAgentActionsForStatus(status)" in source
    assert 'return ["collect", "rename", "cancel"];' in source
    assert 'return ["collect", "rename", "retry"];' in source
    assert 'return ["rename", "retry"];' in source
    assert "function beginChildAgentRename(child)" in source
    assert "function saveChildAgentRename(child)" in source
    assert 'renameInput.addEventListener("keydown"' in source
    assert 'event.key === "Escape"' in source
    assert 'window.prompt("Rename child agent"' not in source


@pytest.mark.parametrize(
    "web_source",
    (
        "scripts/agent_console_template/agent_console_web.py",
        "scripts/norman_codex_web.py",
    ),
)
def test_child_agent_ui_guides_and_guards_child_launches(
    web_source: str,
) -> None:
    source = (Path(__file__).resolve().parents[1] / web_source).read_text(
        encoding="utf-8"
    )

    assert 'id="child-agent-guide-toggle"' in source
    assert 'id="child-agent-guide"' in source
    assert "function setChildAgentGuideOpen(open)" in source
    assert "Norman/Norllama pool policy" in source
    assert 'id="child-agent-objective-feedback"' in source
    assert 'id="child-agent-capacity-note"' in source
    assert 'id="child-agent-patch-acknowledgment"' in source
    assert "const CHILD_AGENT_MIN_OBJECTIVE_CHARACTERS = 12;" in source
    assert "function childAgentObjectiveLength(value)" in source
    assert "function renderChildAgentForm()" in source
    assert "childAgentWriteAcknowledgment.hidden = !patchMode;" in source
    assert "All " + '" + String(limit) + " child-agent slots are active.' in source
    assert 'if (cleanAction === "cancel")' in source
    assert "Any unfinished work will stop." in source
    assert "(event.ctrlKey || event.metaKey) && event.key === " + '"Enter"' in source
    assert 'id="child-agent-status-filter"' in source
    assert 'id="child-agent-search"' in source
    assert 'id="child-agent-filter-clear"' in source
    assert 'data-child-agent-template="investigate"' in source
    assert 'data-child-agent-template="implement"' in source
    assert "const CHILD_AGENT_TEMPLATES = {{" in source
    assert "function childAgentObjectiveReadiness(value)" in source
    assert r"const placeholder = objective.match(/\\[[^\\]\\r\\n]+\\]/);" in source
    assert "Replace " + '" + placeholder[0] + " before launch.' in source
    assert "function applyChildAgentTemplate(key)" in source
    assert "function visibleChildAgents(children)" in source
    assert "function childAgentUpdatedLabel(child, now = Date.now())" in source
    assert 'open: {{ label: "Open child console", icon: "↗" }}' in source
    assert "function openChildAgentConsole(child)" in source
    assert 'const opened = window.open("", "_blank");' in source
    assert "opened.opener = null;" in source
    assert "opened.location.replace(url);" in source
    assert "body.topbar-menu-open .toast-stack," in source
    assert "body.topbar-menu-open .toast-stack .toast" in source
    assert "body.system-open .toast-stack," in source
    assert "body.settings-open .toast-stack," in source
    assert "body.notices-open .toast-stack," in source
    assert "visibility: hidden;" in source


@pytest.mark.parametrize(
    "web_source",
    (
        "scripts/agent_console_template/agent_console_web.py",
        "scripts/norman_codex_web.py",
    ),
)
def test_child_agent_ui_surfaces_attention_and_handoffs(
    web_source: str,
) -> None:
    source = (Path(__file__).resolve().parents[1] / web_source).read_text(
        encoding="utf-8"
    )

    assert 'id="child-agent-summary"' in source
    assert 'class="child-agent-pool-route"' in source
    assert "Pool route</span>" in source
    assert "local-first, capacity managed" in source
    assert "function childAgentSummaryCounts(children)" in source
    assert "function renderChildAgentSummary(children)" in source
    assert "function setChildAgentFilter(filter, options = {{}})" in source
    assert 'handoff: {{ label: "Add result to parent draft", icon: "↳" }}' in source
    assert "function childAgentHasResult(child)" in source
    assert "function childAgentAllowlistedArtifacts(child)" in source
    assert "function addChildAgentResultToParentPrompt(child)" in source
    assert "insertTextIntoPrompt(prefix + handoff, {{ placeAtEnd: true }})" in source
    assert "It has not been sent." in source
    assert "function focusChildAgentWorkbench(target = " + '"objective")' in source
    assert "<kbd>Mod+Shift+A</kbd><span>New child</span>" in source
    assert "<kbd>Mod+Shift+F</kbd><span>Find child</span>" in source
    assert '(lowerKey === "a" || lowerKey === "f")' in source


@pytest.mark.parametrize(
    "web_source",
    (
        "scripts/agent_console_template/agent_console_web.py",
        "scripts/norman_codex_web.py",
    ),
)
def test_web_renderer_renders_root_without_configured_token(
    monkeypatch, web_source: str
) -> None:
    module = _load_web_renderer(web_source)
    monkeypatch.setattr(module, "TOKEN", "")
    monkeypatch.setattr(module, "CANONICAL_HOST", "")

    handler = object.__new__(module.Handler)
    handler.path = "/?profile=dusk"
    handler.headers = Message()
    handler.client_address = ("127.0.0.1", 43123)
    rendered: dict[str, object] = {}
    handler.render_index = lambda params: rendered.update(params=params)
    handler.redirect_root = lambda _params: pytest.fail(
        "an unprotected root request must render instead of redirecting"
    )

    handler.do_GET()

    assert rendered["params"] == {"profile": ["dusk"]}
