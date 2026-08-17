import importlib.util
import pathlib


SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "norllama"
    / "verify_tui_background_inference.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "verify_tui_background_inference_test", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_receipt_is_metadata_only() -> None:
    module = _load_module()

    class Switchboard:
        NORLLAMA_RESIDENT_MODEL = "future-local-model"
        NORLLAMA_RESIDENT_ROLE = {"registry_version": "future-version"}

        @staticmethod
        def local_planner_preflight_readiness():
            return {
                "ready": True,
                "status": "ready",
                "model": "future-local-model",
                "candidate_policy": "resident-role-registry",
            }

        @staticmethod
        def local_planner_preflight(_payload):
            return {
                "used": True,
                "status": "ok",
                "model": "future-local-model",
                "candidate_policy": "resident-role-registry",
                "latency_ms": 12,
                "tokens": 8,
                "summary": "must not be recorded",
            }

        @staticmethod
        def local_planner_verifier(_payload, **_kwargs):
            return {
                "used": True,
                "status": "ok",
                "model": "future-local-model",
                "candidate_policy": "resident-role-registry",
                "latency_ms": 10,
                "tokens": 5,
                "reason": "must not be recorded",
            }

        @staticmethod
        def working_recap_local_llm(_meta, _recap):
            return {"now": "must not be recorded"}, "future-local-model"

    receipt = module.run_acceptance(Switchboard)
    serialized = str(receipt)

    assert receipt["passed"] is True
    assert receipt["resident_model"] == "future-local-model"
    assert receipt["content_recorded"] is False
    assert "must not be recorded" not in serialized
