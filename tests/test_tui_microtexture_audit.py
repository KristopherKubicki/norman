from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_audit():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "tui_microtexture_audit", scripts_dir / "tui_microtexture_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_microtexture_audit"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_microtexture_aliases_cover_legacy_and_common_runtime_names():
    module = _load_audit()

    mapping = module.canonical_texture_map(module.load_cards())

    assert mapping["switchboard"] == "norman"
    assert mapping["subprime"] == "norman"
    assert mapping["studio"] == "autocamera"
    assert mapping["camera-studio"] == "autocamera"
    assert mapping["tv"] == "autocamera"
    assert mapping["dj"] == "phone-ops"
    assert mapping["glimpser"] == "eyebat"
    assert mapping["networking"] == "netops"
    assert mapping["parkergale"] == "pefb"


def test_web_app_texture_audit_only_requires_directory_generated_entries():
    module = _load_audit()

    targets = module.generated_targets_for_item({"kind": "web-app"})

    assert targets == module.JS_GENERATED_TARGETS


def test_js_microtexture_sync_skips_files_without_generated_block():
    module = _load_audit()
    source = "const FLEET_PRIORITY = { norman: 0 };\n"
    rendered = module.texture_sync.render_js_block(module.load_cards())

    assert module.texture_sync.replace_js_block(source, rendered) == source


def test_live_microtexture_audit_has_no_required_coverage_gaps():
    module = _load_audit()

    report = module.build_report()

    assert report["summary"]["required_tuis"] >= 30
    assert report["summary"]["missing"] == 0
    assert report["summary"]["generated_missing"] == 0


def test_microtexture_audit_markdown_includes_alias_and_missing_counts():
    module = _load_audit()

    markdown = module.render_markdown(
        {
            "summary": {
                "texture_cards": 30,
                "required_tuis": 33,
                "direct": 24,
                "aliases": 9,
                "missing": 0,
                "generated_missing": 0,
            },
            "required_rows": [
                {
                    "slug": "studio",
                    "coverage": "alias",
                    "texture": "autocamera",
                    "kind": "ops-console",
                    "principal": "kristopher",
                    "source": "db/estate/registry.yaml",
                }
            ],
        }
    )

    assert "# TUI Microtexture Audit" in markdown
    assert "Alias coverage: 9" in markdown
    assert "Missing coverage: 0" in markdown
    assert "| studio | alias | autocamera | ops-console | kristopher |" in markdown
