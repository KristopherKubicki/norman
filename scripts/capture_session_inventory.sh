#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODE_DIR="$(cd "${ROOT_DIR}/.." && pwd)"
STAMP="$(date +%F)"
OUT_FILE="${ROOT_DIR}/logs/session_inventory_${STAMP}.md"

python3 - "${ROOT_DIR}" "${CODE_DIR}" "${OUT_FILE}" <<'PY'
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
code_dir = Path(sys.argv[2])
out_file = Path(sys.argv[3])
out_file.parent.mkdir(parents=True, exist_ok=True)

now = datetime.now().isoformat(timespec="seconds")


def run(cmd):
    return subprocess.check_output(
        cmd,
        text=True,
        stdin=subprocess.DEVNULL,
        errors="ignore",
    )


def command_exists(name):
    return subprocess.call(
        ["bash", "-lc", f"command -v {name} >/dev/null 2>&1"],
        stdin=subprocess.DEVNULL,
    ) == 0


session_meta = {}
for child in sorted(code_dir.iterdir()):
    if not child.is_dir():
        continue
    session_file = child / ".session"
    if not session_file.exists():
        continue
    try:
        lines = [
            line.strip()
            for line in session_file.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            if line.strip()
        ]
    except OSError:
        continue
    if not lines:
        continue
    tail = lines[-1]
    match = re.search(r"codex resume ([0-9a-f\\-]+)", tail)
    if not match:
        continue
    sid = match.group(1)
    comment = tail.split("#", 1)[1].strip() if "#" in tail else ""
    session_meta[sid] = {
        "project": child.name,
        "hint": comment,
    }

running = []
ps_out = run(["ps", "-eo", "pid,etimes,tty,args", "--sort=-etimes"])
for line in ps_out.splitlines()[1:]:
    line = line.strip()
    if not line:
        continue
    parts = line.split(None, 3)
    if len(parts) < 4:
        continue
    pid_s, et_s, tty, args = parts
    if "codex" not in args:
        continue
    if "codex resume" not in args and "bin/codex" not in args:
        continue
    if "/vendor/" in args and "codex/codex" in args:
        continue
    match = re.search(r"codex resume ([0-9a-f\\-]+)", args)
    sid = match.group(1) if match else "(new/unknown)"
    pid = int(pid_s)
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        cwd = "?"
    running.append(
        {
            "sid": sid,
            "pid": pid,
            "age_s": int(et_s),
            "tty": tty,
            "cwd": cwd,
        }
    )

tmux_sessions = []
tmux_panes = []
if command_exists("tmux"):
    try:
        out = run(
            [
                "tmux",
                "list-sessions",
                "-F",
                "#{session_name}|#{session_windows}|#{session_attached}|#{t:session_created}",
            ]
        )
        for row in out.splitlines():
            if not row.strip():
                continue
            name, windows, attached, created = (
                row.split("|", 3) + ["", "", "", ""]
            )[:4]
            tmux_sessions.append(
                {
                    "name": name,
                    "windows": windows,
                    "attached": attached,
                    "created": created,
                }
            )
    except Exception:
        pass
    try:
        out = run(
            [
                "tmux",
                "list-panes",
                "-a",
                "-F",
                "#{session_name}|#{window_index}.#{pane_index}|#{pane_current_command}|#{pane_current_path}",
            ]
        )
        for row in out.splitlines():
            if not row.strip():
                continue
            session, target, cmd, path = (row.split("|", 3) + ["", "", "", ""])[:4]
            tmux_panes.append(
                {
                    "session": session,
                    "target": target,
                    "cmd": cmd,
                    "path": path,
                }
            )
    except Exception:
        pass

screen_out = ""
if command_exists("screen"):
    proc = subprocess.run(
        ["screen", "-ls"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    screen_out = (proc.stdout or proc.stderr or "").strip()

lines = []
lines.append("# Session Inventory (Live)")
lines.append("")
lines.append(f"- Generated: {now}")
lines.append(f"- Host: {os.uname().nodename}")
lines.append("")
lines.append("## Running Codex Sessions")
lines.append("")
lines.append("| Session ID | Project/CWD | TTY | Age (h) | Rough Work |")
lines.append("|---|---|---:|---:|---|")

if running:
    for item in running:
        sid = item["sid"]
        meta = session_meta.get(sid, {})
        project = meta.get("project", "")
        hint = meta.get("hint", "").strip()
        if not hint:
            name = project or os.path.basename(item["cwd"])
            hint = f"{name} work session"
        project_or_cwd = project or item["cwd"]
        age_h = f"{item['age_s'] / 3600:.1f}"
        lines.append(
            f"| `{sid}` | `{project_or_cwd}` | `{item['tty']}` | {age_h} | {hint} |"
        )
else:
    lines.append("| _none_ | | | | |")

if tmux_sessions:
    pane_by = {}
    for pane in tmux_panes:
        pane_by.setdefault(pane["session"], []).append(pane)
    for sess in tmux_sessions:
        pane = (pane_by.get(sess["name"]) or [{}])[0]
        proj = Path(pane.get("path") or "").name or f"tmux:{sess['name']}"
        lines.append(
            f"| `tmux:{sess['name']}` | `{proj}` | `tmux` | n/a | tmux app/runtime session | pane {pane.get('target', '')} · cmd {pane.get('cmd', '')} |"
        )

lines.append("")
lines.append("## tmux Sessions")
lines.append("")
lines.append("| Session | Windows | Attached | Created | Pane Command | Pane Path |")
lines.append("|---|---:|---:|---|---|---|")

if tmux_sessions:
    pane_by_session = {}
    for pane in tmux_panes:
        pane_by_session.setdefault(pane["session"], []).append(pane)
    for sess in tmux_sessions:
        pane = (pane_by_session.get(sess["name"]) or [{}])[0]
        lines.append(
            f"| `{sess['name']}` | {sess['windows']} | {sess['attached']} | {sess['created']} | `{pane.get('cmd', '')}` | `{pane.get('path', '')}` |"
        )
else:
    lines.append("| _none_ | | | | | |")

lines.append("")
lines.append("## screen Sessions")
lines.append("")
if screen_out:
    lines.append("```text")
    lines.append(screen_out)
    lines.append("```")
else:
    lines.append("- none")

lines.append("")
lines.append("## Notes")
lines.append("")
lines.append("- `new/unknown` means Codex is running without `codex resume <id>` in argv.")
lines.append("- Rough Work comes from `.session` comment hints when available.")

out_file.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print(out_file)
PY

echo "Wrote ${OUT_FILE}"
