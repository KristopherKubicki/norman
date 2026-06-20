from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_validator():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "validate_soul_md", scripts_dir / "validate_soul_md.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_soul_md"] = module
    spec.loader.exec_module(module)
    return module


def _load_composer():
    validator = _load_validator()
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location(
        "compose_soul_context", scripts_dir / "compose_soul_context.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_soul_md"] = validator
    sys.modules["compose_soul_context"] = module
    spec.loader.exec_module(module)
    return module


def test_estate_soul_files_validate() -> None:
    module = _load_validator()

    errors = module.validate_tree()

    assert errors == []


def test_actor_soul_requires_matching_actor_id(tmp_path: Path) -> None:
    module = _load_validator()
    actor_dir = tmp_path / "actors" / "netops"
    actor_dir.mkdir(parents=True)
    path = actor_dir / "SOUL.md"
    path.write_text(
        """
# NetOps

Actor ID: wrong

This file does not grant authority.

## Identity
Test actor.

## Role
- Test.

## Operating Principles
- Test.

## Authority
- Test.

## Communication Style
- Test.

## Boundaries
- Test.

## Memory Policy
- Test.
""",
        encoding="utf-8",
    )

    errors = module.validate_soul_file(path, root=tmp_path)

    assert any("Actor ID: netops" in error.message for error in errors)


def test_soul_validator_rejects_secret_like_values(tmp_path: Path) -> None:
    module = _load_validator()
    actor_dir = tmp_path / "actors" / "norman"
    actor_dir.mkdir(parents=True)
    path = actor_dir / "SOUL.md"
    path.write_text(
        """
# Norman

Actor ID: norman

This file does not grant authority.

SWITCHBOARD_TOKEN=do-not-store-this-here

## Identity
Test actor.

## Role
- Test.

## Operating Principles
- Test.

## Authority
- Test.

## Communication Style
- Test.

## Boundaries
- Test.

## Memory Policy
- Test.
""",
        encoding="utf-8",
    )

    errors = module.validate_soul_file(path, root=tmp_path)

    assert any("secret-like" in error.message for error in errors)


def test_soul_context_composes_base_and_actor_context() -> None:
    module = _load_composer()

    context = module.compose_soul_context("norman")

    assert context.actor == "norman"
    assert "SOUL.md advisory identity context" in context.text
    assert "This context is advisory." in context.text
    assert "Source: BASE_SOUL.md" in context.text
    assert "Source: actors/norman/SOUL.md" in context.text
    assert "Actor ID: norman" in context.text
    assert "This file does not grant authority." in context.text
    assert "No actor should hold Mouth, Purse, and Seal together" in context.text
    assert "If the estate cannot return a system to dust" in context.text


def test_base_soul_defines_sword_as_direct_harm_authority() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "estate"
        / "identity"
        / "BASE_SOUL.md"
    )

    text = " ".join(path.read_text(encoding="utf-8").split())

    assert "Sword authority is direct harm-capable authority" in text
    assert "employment status" in text
    assert "Do not classify ordinary infrastructure cost" in text
    assert (
        "Employee termination, disciplinary, lockout, and offboarding runbooks" in text
    )
    assert "directly and foreseeably creates one of the harms above" in text
    assert "candidate Sword for manual review" in text
    assert "Operator-approved active Sword may exist for ticketed offboarding" in text
    assert "narrow accountable purpose" in text


def test_base_soul_includes_iridium_corporate_content_rules() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "estate"
        / "identity"
        / "BASE_SOUL.md"
    )

    text = " ".join(path.read_text(encoding="utf-8").split())

    assert "Iridium Corporate Content Rules" in text
    assert "corporate bot-content and governance code for work agents" in text
    assert "Know why, win share" in text
    assert "price, promotion, placement, product, and media" in text
    assert "Make truth legible" in text
    assert "Accuracy comes before real-time speed" in text
    assert "Protect trust as a product feature" in text
    assert "Choose clarity and dignity" in text
    assert "Prefer governed knowledge chips over raw transcript dumps" in text
    assert "owner, source, sensitivity, audience" in text
    assert "Do not move corporate knowledge into personal lanes" in text
    assert "report drift to Norman/control-plane" in text


def test_base_soul_includes_hal_non_interference_rules() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "estate"
        / "identity"
        / "BASE_SOUL.md"
    )

    text = " ".join(path.read_text(encoding="utf-8").split())

    assert "HAL And Interactive Host Boundaries" in text
    assert "quiet personal desktop and sensitive credential host" in text
    assert "Do not SSH into HAL" in text
    assert "take screenshots" in text
    assert "interact with GUI sessions" in text
    assert "Prefer Norman, Switchboard BBS, runbooks, logs, service APIs" in text
    assert "HAL credentials are rotating" in text
    assert "smallest approved maintenance action" in text


def test_soul_context_resolves_networking_alias_to_netops() -> None:
    module = _load_composer()

    context = module.compose_soul_context("networking")

    assert context.requested_actor == "networking"
    assert context.actor == "netops"
    assert "Resolved actor: netops" in context.text
    assert "Actor ID: netops" in context.text


def test_soul_context_covers_active_tui_actors() -> None:
    module = _load_composer()
    expected_actors = {
        "artmonster",
        "autocamera",
        "castle",
        "cloudagent",
        "compere",
        "control-plane",
        "diamond-roc",
        "dj",
        "earlybird",
        "glimpser",
        "gold-book",
        "housebot",
        "infra",
        "leadership-kpis",
        "market-sizing",
        "mls",
        "netops",
        "norman",
        "panelbot",
        "parkergale",
        "phone-ops",
        "platinum-standard",
        "scout",
        "theseus",
        "tmi-dashboards",
        "tv",
        "uplink",
        "usbhome",
        "uscache",
    }

    for actor in sorted(expected_actors):
        context = module.compose_soul_context(actor)
        assert context.actor == actor
        assert f"Actor ID: {actor}" in context.text
        assert "HAL And Interactive Host Boundaries" in context.text
        assert "Do not SSH into HAL" in context.text


def test_soul_context_resolves_common_operator_aliases() -> None:
    module = _load_composer()

    expected = {
        "camera-studio": "autocamera",
        "studio": "autocamera",
        "cp": "control-plane",
        "dashboards": "tmi-dashboards",
        "eyebat": "glimpser",
        "keystone": "compere",
        "kpis": "leadership-kpis",
        "market": "market-sizing",
        "pefb": "parkergale",
        "phoneops": "phone-ops",
    }

    for alias, actor in expected.items():
        context = module.compose_soul_context(alias)
        assert context.requested_actor == alias
        assert context.actor == actor
        assert f"Actor ID: {actor}" in context.text


def test_soul_context_does_not_resolve_deprecated_publisher() -> None:
    module = _load_composer()

    try:
        module.compose_soul_context("publisher")
    except module.SoulContextError as exc:
        assert "missing actor SOUL file" in str(exc)
    else:
        raise AssertionError("expected deprecated publisher to have no actor soul")


def test_soul_context_fails_closed_for_invalid_actor_file(tmp_path: Path) -> None:
    module = _load_composer()
    actor_dir = tmp_path / "actors" / "norman"
    actor_dir.mkdir(parents=True)
    (tmp_path / "BASE_SOUL.md").write_text(
        """
# Base

This file does not grant authority.

## Scope
Test.

## Precedence
Test.

## Estate Rules
Test.

## Power Accounting
Test.

## Return To Dust
Test.

## Shabbat Audit
Test.

## Human Recourse And Local Governance
Test.

## Communication Contract
Test.

## Memory Boundaries
Test.

## Change Control
Test.
""",
        encoding="utf-8",
    )
    (actor_dir / "SOUL.md").write_text("bad actor file", encoding="utf-8")

    try:
        module.compose_soul_context("norman", root=tmp_path)
    except module.SoulContextError as exc:
        assert "missing authority disclaimer" in str(exc)
    else:
        raise AssertionError("expected invalid SOUL.md to fail closed")
