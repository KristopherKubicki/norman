#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_JSON = ROOT / "app/static/textures/tui_microtexture_reference.json"

PYTHON_TARGETS = (
    ROOT / "scripts/agent_console_template/agent_console_web.py",
    ROOT / "scripts/norman_codex_web.py",
)
JS_TARGETS = (
    ROOT / "app/static/js/home.js",
    ROOT / "app/static/js/systems.js",
)

PY_BEGIN = "# BEGIN GENERATED TUI MICROTEXTURE OVERRIDES"
PY_END = "# END GENERATED TUI MICROTEXTURE OVERRIDES"
JS_BEGIN = "  // BEGIN GENERATED TUI MICROTEXTURES"
JS_END = "  // END GENERATED TUI MICROTEXTURES"

PYTHON_ALIASES = {
    "norman": ("switchboard", "subprime"),
    "eyebat": ("glimpser",),
    "autocamera": ("studio", "camera-studio", "tv"),
    "phone-ops": ("dj",),
    "keystone": ("compere",),
    "netops": ("networking",),
    "pefb": ("parkergale",),
}

DIRECTORY_ALIASES = {
    "norman": ("norman-service", "switchboard", "subprime"),
    "eyebat": ("glimpser",),
    "autocamera": ("studio", "camera-studio", "tv"),
    "phone-ops": ("dj",),
    "keystone": ("compere",),
    "leadership-kpis": ("kpis",),
    "netops": ("networking",),
    "pefb": ("parkergale",),
}

DIRECTORY_ACCENT_ALPHA = {
    "control-plane": 0.050,
    "gold-book": 0.050,
    "dohio": 0.052,
}

EXTRA_DIRECTORY_TEXTURES = (
    (
        "finance-reader",
        {
            "angle": 35,
            "crossAngle": 125,
            "grain": 28,
            "crossGrain": 40,
            "glowX": 24,
            "accent": "rgba(110, 231, 183, 0.042)",
        },
    ),
    (
        "health-reader",
        {
            "angle": 64,
            "crossAngle": 154,
            "grain": 24,
            "crossGrain": 32,
            "glowX": 62,
            "accent": "rgba(167, 243, 208, 0.040)",
        },
    ),
    (
        "work-special",
        {
            "angle": 28,
            "crossAngle": 118,
            "grain": 20,
            "crossGrain": 28,
            "glowX": 18,
            "accent": "rgba(250, 204, 21, 0.052)",
        },
    ),
    (
        "work-special-home",
        {
            "angle": 28,
            "crossAngle": 118,
            "grain": 20,
            "crossGrain": 28,
            "glowX": 18,
            "accent": "rgba(250, 204, 21, 0.052)",
        },
    ),
    (
        "d-ace",
        {
            "angle": 154,
            "crossAngle": 64,
            "grain": 32,
            "crossGrain": 20,
            "glowX": 80,
            "accent": "rgba(99, 102, 241, 0.040)",
        },
    ),
    (
        "acast",
        {
            "angle": 110,
            "crossAngle": 20,
            "grain": 28,
            "crossGrain": 36,
            "glowX": 66,
            "accent": "rgba(244, 114, 182, 0.042)",
        },
    ),
)


def load_cards() -> list[dict]:
    with REFERENCE_JSON.open(encoding="utf-8") as handle:
        cards = json.load(handle)
    if not isinstance(cards, list):
        raise ValueError(f"{REFERENCE_JSON} must contain a list of texture cards")
    for card in cards:
        for key in (
            "slug",
            "colors",
            "angle",
            "cross",
            "grain",
            "cross_grain",
            "glow",
            "texture_alpha",
        ):
            if key not in card:
                raise ValueError(f"Texture card missing {key!r}: {card!r}")
    return cards


def iter_with_aliases(
    cards: list[dict], aliases: dict[str, tuple[str, ...]]
) -> Iterable[tuple[str, dict]]:
    for card in cards:
        slug = str(card["slug"])
        yield slug, card
        for alias in aliases.get(slug, ()):
            yield alias, card


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid hex color: {hex_color!r}")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def fmt_opacity(value: float) -> str:
    return f"{value:.2f}"


def pattern_detail_vars(card: dict, alpha: float) -> dict[str, str]:
    pattern = str(card.get("pattern") or "").lower()
    line_factor = 0.48
    cross_factor = 0.24
    dot_factor = 0.11
    rail_factor = 0.38
    band_factor = 0.08
    if any(term in pattern for term in ("scan", "pixels", "pin", "grid")):
        line_factor = 0.56
        cross_factor = 0.28
        dot_factor = 0.18
        rail_factor = 0.40
        band_factor = 0.14
    elif any(term in pattern for term in ("weave", "mesh", "lattice", "plaid")):
        line_factor = 0.54
        cross_factor = 0.34
        dot_factor = 0.13
        rail_factor = 0.36
        band_factor = 0.10
    elif any(term in pattern for term in ("stone", "book", "platinum", "memo")):
        line_factor = 0.44
        cross_factor = 0.30
        dot_factor = 0.08
        rail_factor = 0.52
        band_factor = 0.14
    elif any(term in pattern for term in ("aperture", "contour", "field", "sweep")):
        line_factor = 0.50
        cross_factor = 0.22
        dot_factor = 0.14
        rail_factor = 0.34
        band_factor = 0.10
    return {
        "texture-glow-x": f"{int(card['glow'][0])}%",
        "texture-glow-y": f"{int(card['glow'][1])}%",
        "identity-line-opacity": fmt_opacity(alpha * line_factor),
        "identity-cross-opacity": fmt_opacity(alpha * cross_factor),
        "identity-dot-opacity": fmt_opacity(alpha * dot_factor),
        "identity-rail-opacity": fmt_opacity(alpha * rail_factor),
        "identity-band-opacity": fmt_opacity(alpha * band_factor),
    }


def texture_vars(card: dict) -> dict[str, str]:
    alpha = float(card["texture_alpha"])
    values = {
        "texture-angle": f"{int(card['angle'])}deg",
        "texture-cross-angle": f"{int(card['cross'])}deg",
        "texture-spacing": f"{int(card['grain'])}px",
        "texture-cross-spacing": f"{int(card['cross_grain'])}px",
        "page-texture-opacity": fmt_opacity(alpha * 0.32),
        "page-cross-texture-opacity": fmt_opacity(alpha * 0.14),
        "chrome-detail-opacity": fmt_opacity(alpha * 0.28),
        "brand-wash-opacity": fmt_opacity(alpha * 0.36),
        "composer-detail-opacity": "0",
        "composer-cross-detail-opacity": "0",
        "focus-detail-opacity": fmt_opacity(alpha * 0.28),
        "message-detail-opacity": "0",
        "agent-accent-3": str(card["colors"][2]),
    }
    values.update(pattern_detail_vars(card, alpha))
    return values


def render_python_block(cards: list[dict]) -> str:
    lines = [
        PY_BEGIN,
        "AGENT_TEXTURE_OVERRIDES = {",
    ]
    for slug, card in iter_with_aliases(cards, PYTHON_ALIASES):
        lines.append(f'    "{slug}": {{')
        for key, value in texture_vars(card).items():
            lines.append(f'        "{key}": "{value}",')
        lines.append("    },")
    lines.extend(["}", PY_END])
    return "\n".join(lines)


def directory_spec(card: dict, slug: str) -> dict[str, int | str]:
    r, g, b = hex_to_rgb(str(card["colors"][0]))
    alpha = DIRECTORY_ACCENT_ALPHA.get(slug, 0.044)
    return {
        "angle": int(card["angle"]),
        "crossAngle": int(card["cross"]),
        "grain": int(card["grain"]),
        "crossGrain": int(card["cross_grain"]),
        "glowX": int(card["glow"][0]),
        "accent": f"rgba({r}, {g}, {b}, {alpha:.3f})",
    }


def render_js_spec(slug: str, spec: dict[str, int | str]) -> str:
    return (
        f"    '{slug}': {{ angle: {spec['angle']}, crossAngle: {spec['crossAngle']}, "
        f"grain: {spec['grain']}, crossGrain: {spec['crossGrain']}, "
        f"glowX: {spec['glowX']}, accent: '{spec['accent']}' }},"
    )


def render_js_block(cards: list[dict]) -> str:
    lines = [
        JS_BEGIN,
        "  const NAMED_TUI_TEXTURES = {",
    ]
    for slug, card in iter_with_aliases(cards, DIRECTORY_ALIASES):
        lines.append(render_js_spec(slug, directory_spec(card, slug)))
    for slug, spec in EXTRA_DIRECTORY_TEXTURES:
        lines.append(render_js_spec(slug, spec))
    lines.extend(["  };", JS_END])
    return "\n".join(lines)


def replace_python_block(source: str, block: str) -> str:
    marker_pattern = re.compile(
        rf"{re.escape(PY_BEGIN)}\n.*?\n{re.escape(PY_END)}",
        flags=re.DOTALL,
    )
    if marker_pattern.search(source):
        return marker_pattern.sub(block, source, count=1)

    legacy_pattern = re.compile(
        r"AGENT_TEXTURE_OVERRIDES = \{\n.*?\n\}\n(?=\nFALLBACK_PROFILE_ORDER = \()",
        flags=re.DOTALL,
    )
    if not legacy_pattern.search(source):
        raise ValueError("Could not locate AGENT_TEXTURE_OVERRIDES block")
    return legacy_pattern.sub(block, source, count=1)


def replace_js_block(source: str, block: str) -> str:
    marker_pattern = re.compile(
        rf"{re.escape(JS_BEGIN)}\n.*?\n{re.escape(JS_END)}",
        flags=re.DOTALL,
    )
    if marker_pattern.search(source):
        return marker_pattern.sub(block, source, count=1)

    legacy_pattern = re.compile(
        r"  const NAMED_TUI_TEXTURES = \{\n.*?\n  \};\n(?=\n  const TUI_TEXTURE_ACCENTS = \{)",
        flags=re.DOTALL,
    )
    if not legacy_pattern.search(source):
        return source
    return legacy_pattern.sub(block + "\n", source, count=1)


def sync_file(path: Path, rendered: str, *, check: bool) -> bool:
    source = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        updated = replace_python_block(source, rendered)
    else:
        updated = replace_js_block(source, rendered)
    if updated == source:
        return False
    if check:
        print(f"drift: {path.relative_to(ROOT)}", file=sys.stderr)
        return True
    path.write_text(updated, encoding="utf-8")
    print(f"updated: {path.relative_to(ROOT)}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync TUI microtexture constants from the contact-sheet JSON."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if generated sections differ instead of writing updates",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cards = load_cards()
    python_block = render_python_block(cards)
    js_block = render_js_block(cards)

    drifted = False
    for path in PYTHON_TARGETS:
        drifted = sync_file(path, python_block, check=args.check) or drifted
    for path in JS_TARGETS:
        drifted = sync_file(path, js_block, check=args.check) or drifted

    if args.check and drifted:
        return 1
    if not drifted:
        print("microtexture generated sections are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
