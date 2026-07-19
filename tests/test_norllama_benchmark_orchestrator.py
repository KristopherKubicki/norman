import importlib.util
import sys
from pathlib import Path


def _load_module():
    script = Path("scripts/norllama_benchmark_orchestrator.py")
    spec = importlib.util.spec_from_file_location(
        "norllama_benchmark_orchestrator", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["norllama_benchmark_orchestrator"] = module
    spec.loader.exec_module(module)
    return module


def test_orchestrator_defers_publish_until_dependencies_complete() -> None:
    module = _load_module()
    plan = {
        "schema": "norman.norllama.benchmark-orchestration-plan.v1",
        "plan_id": "column-fill",
        "tasks": [
            {"id": "bench", "command": ["true"], "max_attempts": 2},
            {"id": "publish", "command": ["true"], "depends_on": ["bench"]},
        ],
    }
    state = module.new_state(plan)

    assert module.ready_task_ids(plan, state) == ["bench"]
    module.apply_task_result(
        state=state,
        task=plan["tasks"][0],
        returncode=0,
    )
    assert module.ready_task_ids(plan, state) == ["publish"]


def test_orchestrator_marks_downstream_task_blocked_after_terminal_failure() -> None:
    module = _load_module()
    plan = {
        "tasks": [
            {"id": "bench", "command": ["false"], "max_attempts": 1},
            {"id": "publish", "command": ["true"], "depends_on": ["bench"]},
        ]
    }
    state = module.new_state(plan)
    module.apply_task_result(state=state, task=plan["tasks"][0], returncode=1)

    assert state["tasks"]["bench"]["state"] == "failed"
    assert module.ready_task_ids(plan, state) == []
    assert state["tasks"]["publish"]["state"] == "blocked"
