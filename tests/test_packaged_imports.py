import importlib
import sys


def test_route_proof_modules_import_without_path_mutation():
    before = list(sys.path)

    for module in (
        "app.services.norllama.routing",
        "app.services.norllama.route_proof",
        "app.services.norllama.warm_policy",
        "app.services.console_runtime.worker",
    ):
        importlib.import_module(module)

    assert sys.path == before
