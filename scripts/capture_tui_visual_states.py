#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "scripts/agent_console_template/agent_console_web.py"
DEFAULT_OUT_DIR = ROOT / "tmp/tui_visual_states"

AGENT_LABELS = {
    "norman": "Norman",
    "panelbot": "PanelBot",
    "cloudagent": "CloudAgent",
    "dohio": "Dohio",
}

AGENT_GROUPS = {
    "norman": "norman",
    "panelbot": "work",
    "cloudagent": "shared",
    "dohio": "shared",
}

VIEWPORTS = {
    "desktop": (1440, 1000),
    "mobile": (390, 844),
}

CHROME_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


class _Headers(dict):
    def get(self, key: str, default: str = "") -> str:
        return str(super().get(key, default))


def parse_csv(value: str, *, allowed: set[str] | None = None) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if allowed is not None:
        unknown = [item for item in items if item not in allowed]
        if unknown:
            raise SystemExit(f"unknown value(s): {', '.join(unknown)}")
    return items


def find_browser() -> str | None:
    for candidate in CHROME_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def load_console_module(agent: str):
    label = AGENT_LABELS.get(agent, agent.replace("-", " ").title())
    env_updates = {
        "NORMAN_CODEX_AGENT_SLUG": agent,
        "NORMAN_CODEX_AGENT_NAME": label,
        "NORMAN_CODEX_AGENT_GROUP": AGENT_GROUPS.get(agent, "work"),
        "NORMAN_CODEX_AUTH_TOKEN": "visual-capture-token",
        "NORMAN_CODEX_UI_VERSION": "visual-capture",
    }
    previous = {key: os.environ.get(key) for key in env_updates}
    os.environ.update(env_updates)
    try:
        module_name = f"_tui_visual_capture_{agent.replace('-', '_')}_{time.time_ns()}"
        spec = importlib.util.spec_from_file_location(module_name, TEMPLATE_PATH)
        if not spec or not spec.loader:
            raise RuntimeError(f"could not load {TEMPLATE_PATH}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def draft_attachments_for_state(state: str) -> list[dict[str, Any]]:
    if state != "attachments":
        return []
    return [
        {
            "token": "visual-upload-zip",
            "name": "retailer_category_walk.zip",
            "size": 71_100_000,
            "content_type": "application/zip",
            "kind": "file",
            "source": "upload",
        },
        {
            "token": "visual-upload-image",
            "name": "panelbot_reference.png",
            "size": 1_200_000,
            "content_type": "image/png",
            "kind": "image",
            "source": "upload",
            "path": "/tmp/visual/panelbot_reference.png",
        },
    ]


def history_for_state(state: str) -> list[dict[str, str]]:
    base = [
        {
            "role": "user",
            "content": "Can you make the TUI header and composer feel solid on mobile and desktop?",
        },
        {
            "role": "assistant",
            "content": (
                "I tightened the header cartouche, kept the composer stable while typing, "
                "and preserved attachment feedback in the input rail."
            ),
        },
    ]
    if state == "media":
        base.extend(
            [
                {
                    "role": "user",
                    "content": "Here is the episode closeout package and replay media.",
                },
                {
                    "role": "assistant",
                    "content": (
                        "I found media links that should render inline: "
                        "[episode audio](/files/replay.mp3), "
                        "[walkthrough video](/files/walkthrough.mp4), and "
                        "[reference frame](/files/frame.png)."
                    ),
                },
            ]
        )
    return base


def snapshot_for_state(state: str) -> dict[str, Any]:
    running = state == "running"
    attachments = draft_attachments_for_state(state)
    return {
        "pending": running,
        "thread_id": "visual-capture-thread",
        "updated_at": int(time.time()),
        "services": [
            {"name": "codex-web", "status": "active"},
            {"name": "agent-console", "status": "active"},
        ],
        "last_prompt": "Polish the header/cartouche and input box.",
        "last_response": "Visual capture fixture ready.",
        "last_error": "[none]",
        "pane": "[visual capture fixture]",
        "logs": "[visual capture fixture]",
        "history": history_for_state(state),
        "queued_prompts": (
            [
                {
                    "id": "visual-queued-prompt",
                    "message": "Then check mobile scrolling while typing.",
                    "created_at": int(time.time()),
                }
            ]
            if running
            else []
        ),
        "queue_depth": 1 if running else 0,
        "draft_attachments": attachments,
        "usage": {
            "total_tokens": 42800,
            "input_tokens": 31200,
            "output_tokens": 11600,
            "cost_usd": 0.0,
        },
    }


def render_index_html(agent: str, state: str, viewport: str) -> str:
    module = load_console_module(agent)
    snapshot = snapshot_for_state(state)
    module.ensure_session = lambda: None
    module.current_snapshot = lambda: snapshot
    module.STATE_DIR = Path(tempfile.mkdtemp(prefix="tui-visual-state-"))
    module.load_draft_attachments = lambda: list(snapshot["draft_attachments"])

    handler = object.__new__(module.Handler)
    handler.wfile = io.BytesIO()
    handler.headers = _Headers({"Host": f"{agent}.visual-capture.test"})
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None
    handler.is_trusted_client = lambda: False
    handler.browser_auth_supported_for_request = lambda: False
    handler.auth_cookie_token = lambda: ""

    module.Handler.render_index(handler, {"token": ["visual-capture-token"]})
    rendered = handler.wfile.getvalue().decode("utf-8")
    return inject_capture_metadata(
        rendered, agent=agent, state=state, viewport=viewport
    )


def inject_capture_metadata(
    rendered: str, *, agent: str, state: str, viewport: str
) -> str:
    metadata = {
        "agent": agent,
        "state": state,
        "viewport": viewport,
        "generated_by": "scripts/capture_tui_visual_states.py",
    }
    style = """
<style id="visual-capture-metadata-style">
  html[data-visual-capture="true"] body::before {
    content: attr(data-visual-agent) " / " attr(data-visual-state) " / " attr(data-visual-viewport);
    position: fixed;
    left: 8px;
    bottom: 8px;
    z-index: 100000;
    padding: 4px 7px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.86);
    color: #26313f;
    border: 1px solid rgba(38, 49, 63, 0.16);
    font: 11px/1.2 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    pointer-events: none;
  }
</style>
"""
    script = f"""
<script id="visual-capture-metadata">
  window.__TUI_VISUAL_CAPTURE__ = {json.dumps(metadata, sort_keys=True)};
  document.documentElement.dataset.visualCapture = "true";
  document.documentElement.dataset.visualViewport = {json.dumps(viewport)};
  document.body.dataset.visualAgent = {json.dumps(agent)};
  document.body.dataset.visualState = {json.dumps(state)};
  document.body.dataset.visualViewport = {json.dumps(viewport)};
  document.body.classList.add("visual-capture-state", "visual-capture-{state}");
  if ({json.dumps(state != "idle")}) {{
    document.body.classList.add("chat-scrolled");
  }}
  window.addEventListener("DOMContentLoaded", () => {{
    const prompt = document.getElementById("prompt-input");
    if (prompt) {{
      prompt.value = {json.dumps(prompt_text_for_state(state))};
      prompt.dispatchEvent(new Event("input", {{ bubbles: true }}));
      if ({json.dumps(state in {"attachments", "running"})}) {{
        prompt.focus({{ preventScroll: true }});
      }}
    }}
  }});
</script>
"""
    rendered = rendered.replace("</head>", f"{style}</head>", 1)
    return rendered.replace("</body>", f"{script}</body>", 1)


def prompt_text_for_state(state: str) -> str:
    if state == "attachments":
        return (
            "Use the staged files and tell me exactly what will happen before sending."
        )
    if state == "running":
        return "Queue this as the next prompt after the active job finishes."
    if state == "media":
        return "Embed the player inline here so I do not have to open another view."
    return "Tighten the TUI polish without moving the viewport while I type."


def capture_png(
    browser: str, html_path: Path, output_path: Path, size: tuple[int, int]
) -> None:
    width, height = size
    command = [
        browser,
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={width},{height}",
        "--virtual-time-budget=1200",
        f"--screenshot={output_path}",
        html_path.resolve().as_uri(),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture representative TUI header/composer visual states."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--agents",
        default="norman,panelbot,cloudagent,dohio",
        help="comma-separated agent slugs to capture",
    )
    parser.add_argument(
        "--states",
        default="idle,running,attachments,media",
        help="comma-separated states: idle,running,attachments,media",
    )
    parser.add_argument(
        "--viewports",
        default="desktop,mobile",
        help="comma-separated viewport names: desktop,mobile",
    )
    parser.add_argument(
        "--html-only",
        action="store_true",
        help="write HTML fixtures but skip browser screenshot capture",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    agents = parse_csv(args.agents)
    states = parse_csv(args.states, allowed={"idle", "running", "attachments", "media"})
    viewports = parse_csv(args.viewports, allowed=set(VIEWPORTS))
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    browser = None if args.html_only else find_browser()
    entries: list[dict[str, Any]] = []
    for agent in agents:
        for state in states:
            for viewport in viewports:
                width, height = VIEWPORTS[viewport]
                stem = f"{agent}-{state}-{viewport}"
                html_path = out_dir / f"{stem}.html"
                png_path = out_dir / f"{stem}.png"
                html_path.write_text(
                    render_index_html(agent, state, viewport),
                    encoding="utf-8",
                )
                screenshot_path = None
                screenshot_error = None
                if browser:
                    try:
                        capture_png(browser, html_path, png_path, (width, height))
                        screenshot_path = str(png_path)
                    except subprocess.CalledProcessError as exc:
                        screenshot_error = exc.stderr or exc.stdout or str(exc)
                entries.append(
                    {
                        "agent": agent,
                        "state": state,
                        "viewport": viewport,
                        "width": width,
                        "height": height,
                        "html": str(html_path),
                        "screenshot": screenshot_path,
                        "screenshot_error": screenshot_error,
                    }
                )

    manifest = {
        "generated_at": int(time.time()),
        "browser": browser,
        "html_only": bool(args.html_only),
        "entries": entries,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(entries)} visual states to {out_dir}")
    if not args.html_only and not browser:
        print(
            "no Chromium/Chrome binary found; HTML fixtures were written without PNGs"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
