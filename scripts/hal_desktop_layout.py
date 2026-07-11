#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import json
import re
import subprocess
import sys
import time
from ctypes import Structure, Union, c_char_p, c_int, c_long, c_ulong
from pathlib import Path
from typing import Any


CLIENT_MESSAGE = 33
SUBSTRUCTURE_NOTIFY_MASK = 1 << 19
SUBSTRUCTURE_REDIRECT_MASK = 1 << 20
NORTH_WEST_GRAVITY = 1
MOVERESIZE_X = 1 << 8
MOVERESIZE_Y = 1 << 9
MOVERESIZE_WIDTH = 1 << 10
MOVERESIZE_HEIGHT = 1 << 11


def run_text(*args: str) -> str:
    return subprocess.check_output(list(args), text=True, stderr=subprocess.DEVNULL)


def parse_root_windows() -> tuple[list[str], str | None]:
    root = run_text("xprop", "-root", "_NET_CLIENT_LIST", "_NET_ACTIVE_WINDOW")
    client_match = re.search(r"_NET_CLIENT_LIST\(WINDOW\): window id # (.+)", root)
    active_match = re.search(
        r"_NET_ACTIVE_WINDOW\(WINDOW\): window id # (0x[0-9a-f]+)", root
    )
    ids = re.findall(r"0x[0-9a-f]+", client_match.group(1) if client_match else "")
    active = active_match.group(1) if active_match else None
    return ids, active


def parse_frame_extents(raw: str) -> list[int] | None:
    match = re.search(r"_GTK_FRAME_EXTENTS\(CARDINAL\) = ([0-9, ]+)", raw)
    if not match:
        return None
    return [int(value.strip()) for value in match.group(1).split(",")]


def parse_window_geometry(window_id: str) -> dict[str, int]:
    output = run_text("xwininfo", "-id", window_id)
    values: dict[str, int] = {}
    for line in output.splitlines():
        if "Absolute upper-left X:" in line:
            values["x"] = int(line.split(":", 1)[1])
        elif "Absolute upper-left Y:" in line:
            values["y"] = int(line.split(":", 1)[1])
        elif "Width:" in line and "width" not in values:
            values["width"] = int(line.split(":", 1)[1])
        elif "Height:" in line and "height" not in values:
            values["height"] = int(line.split(":", 1)[1])
    return values


def normalize_title(title: str) -> str:
    value = title.strip()
    value = re.sub(r"^\(\d+\)\s+", "", value)
    value = re.sub(r"^[!■○●⠧⠙⠇]+\s*", "", value)
    value = value.replace(" - Google Chrome", "")
    return value.strip()


def match_hint(title: str) -> str:
    normalized = normalize_title(title)
    if " Console" in normalized:
        return normalized.split(" Console", 1)[0].strip()
    if " | CloudWatch | " in normalized:
        return normalized.split(" | CloudWatch | ", 1)[0].strip()
    if " - Slack" in normalized:
        return normalized.split(" - Slack", 1)[0].strip()
    if " - YouTube" in normalized:
        return normalized.split(" - YouTube", 1)[0].strip()
    if " | " in normalized:
        return normalized.split(" | ", 1)[0].strip()
    return normalized[:96].strip()


def current_windows() -> list[dict[str, Any]]:
    ids, active = parse_root_windows()
    items: list[dict[str, Any]] = []
    for window_id in ids:
        try:
            meta = run_text(
                "xprop",
                "-id",
                window_id,
                "_NET_WM_NAME",
                "WM_CLASS",
                "_GTK_FRAME_EXTENTS",
            )
            geometry = parse_window_geometry(window_id)
        except subprocess.CalledProcessError:
            continue
        title_match = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "(.*)"', meta)
        class_match = re.search(r"WM_CLASS\(STRING\) = (.+)", meta)
        title = title_match.group(1) if title_match else ""
        wm_class = class_match.group(1).strip() if class_match else ""
        items.append(
            {
                "window_id": window_id,
                "title": title,
                "normalized_title": normalize_title(title),
                "match_hint": match_hint(title),
                "wm_class": wm_class,
                "frame_extents": parse_frame_extents(meta),
                "active": window_id == active,
                **geometry,
            }
        )
    return items


def monitors() -> list[dict[str, Any]]:
    output = run_text("xrandr", "--current")
    items: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = re.match(
            r"^([A-Za-z0-9-]+)\s+connected(?: primary)?\s+(\d+)x(\d+)\+(\d+)\+(\d+)",
            line,
        )
        if not match:
            continue
        name, width, height, x, y = match.groups()
        items.append(
            {
                "name": name,
                "width": int(width),
                "height": int(height),
                "x": int(x),
                "y": int(y),
                "raw": line.strip(),
            }
        )
    return items


def capture_snapshot(output_path: Path) -> None:
    payload = {
        "captured_at": run_text("date", "-u", "+%Y-%m-%dT%H:%M:%SZ").strip(),
        "host": run_text("hostname").strip(),
        "workarea": run_text("xprop", "-root", "_NET_WORKAREA").strip(),
        "monitors": monitors(),
        "windows": current_windows(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class XClientMessageDataLong(ctypes.Array):
    _length_ = 5
    _type_ = c_long


class XClientMessageData(Union):
    _fields_ = [("l", XClientMessageDataLong)]


class XClientMessageEvent(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", ctypes.c_void_p),
        ("window", c_ulong),
        ("message_type", c_ulong),
        ("format", c_int),
        ("data", XClientMessageData),
    ]


class XEvent(Union):
    _fields_ = [("xclient", XClientMessageEvent), ("pad", c_long * 24)]


def move_resize_window(window_id: str, x: int, y: int, width: int, height: int) -> None:
    x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, c_char_p, c_int]
    x11.XInternAtom.restype = c_ulong
    x11.XSendEvent.argtypes = [
        ctypes.c_void_p,
        c_ulong,
        c_int,
        c_long,
        ctypes.POINTER(XEvent),
    ]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Unable to open X display")
    try:
        root = x11.XDefaultRootWindow(display)
        atom = x11.XInternAtom(display, b"_NET_MOVERESIZE_WINDOW", 0)
        event = XEvent()
        event.xclient.type = CLIENT_MESSAGE
        event.xclient.serial = 0
        event.xclient.send_event = 1
        event.xclient.display = display
        event.xclient.window = int(window_id, 16)
        event.xclient.message_type = atom
        event.xclient.format = 32
        event.xclient.data.l[0] = (
            NORTH_WEST_GRAVITY
            | MOVERESIZE_X
            | MOVERESIZE_Y
            | MOVERESIZE_WIDTH
            | MOVERESIZE_HEIGHT
        )
        event.xclient.data.l[1] = x
        event.xclient.data.l[2] = y
        event.xclient.data.l[3] = width
        event.xclient.data.l[4] = height
        x11.XSendEvent(
            display,
            root,
            0,
            SUBSTRUCTURE_REDIRECT_MASK | SUBSTRUCTURE_NOTIFY_MASK,
            ctypes.byref(event),
        )
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)


def score_match(snapshot_window: dict[str, Any], live_window: dict[str, Any]) -> int:
    if snapshot_window.get("wm_class") != live_window.get("wm_class"):
        return -1
    snapshot_title = str(snapshot_window.get("normalized_title") or "")
    snapshot_hint = str(snapshot_window.get("match_hint") or "")
    live_title = str(live_window.get("normalized_title") or "")
    live_hint = str(live_window.get("match_hint") or "")
    if snapshot_title and live_title and snapshot_title == live_title:
        return 100
    if snapshot_hint and live_hint and snapshot_hint == live_hint:
        return 90
    if snapshot_hint and snapshot_hint in live_title:
        return 80
    if live_hint and live_hint in snapshot_title:
        return 70
    return -1


def restore_snapshot(snapshot_path: Path, pause_ms: int) -> None:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot_windows = payload.get("windows") or []
    live_windows = current_windows()
    used: set[str] = set()
    moved: list[tuple[str, str]] = []

    for snapshot_window in snapshot_windows:
        candidates = []
        for live_window in live_windows:
            if live_window["window_id"] in used:
                continue
            score = score_match(snapshot_window, live_window)
            if score >= 0:
                candidates.append((score, live_window))
        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[0], item[1]["window_id"]))
        matched = candidates[0][1]
        used.add(matched["window_id"])
        move_resize_window(
            matched["window_id"],
            int(snapshot_window["x"]),
            int(snapshot_window["y"]),
            int(snapshot_window["width"]),
            int(snapshot_window["height"]),
        )
        moved.append((snapshot_window["title"], matched["window_id"]))
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)

    print(json.dumps({"snapshot": str(snapshot_path), "moved": moved}, indent=2))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture or restore the current hal desktop layout."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser(
        "capture", help="Capture the current desktop layout to JSON."
    )
    capture_parser.add_argument("output", type=Path, help="Snapshot JSON path.")

    restore_parser = subparsers.add_parser(
        "restore", help="Restore a desktop layout snapshot."
    )
    restore_parser.add_argument("snapshot", type=Path, help="Snapshot JSON path.")
    restore_parser.add_argument(
        "--pause-ms",
        type=int,
        default=50,
        help="Pause between move operations to keep GNOME from dropping events.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.command == "capture":
        capture_snapshot(args.output)
        return 0
    if args.command == "restore":
        restore_snapshot(args.snapshot, pause_ms=args.pause_ms)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
