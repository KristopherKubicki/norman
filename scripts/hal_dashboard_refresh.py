#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import Structure, Union, c_char_p, c_int, c_long, c_uint, c_ulong
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hal_desktop_layout import (
    CLIENT_MESSAGE,
    SUBSTRUCTURE_NOTIFY_MASK,
    SUBSTRUCTURE_REDIRECT_MASK,
    current_windows,
    parse_root_windows,
)

DEFAULT_SETTLE_MS = 250
DEFAULT_BETWEEN_MS = 700
DEFAULT_INTERVAL_SECONDS = 300


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


def refresh_reason_for_title(title: str) -> str | None:
    clean = str(title or "").strip().lower()
    if not clean:
        return None
    if "console" in clean or "slack" in clean or "youtube" in clean:
        return None
    if " | cloudwatch | " in clean:
        return "cloudwatch"
    if "dashboard" in clean:
        return "dashboard"
    if "| autocamera" in clean:
        return "autocamera"
    return None


def candidate_windows() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for window in current_windows():
        title = str(window.get("title") or "")
        reason = refresh_reason_for_title(title)
        if not reason:
            continue
        items.append(
            {
                "window_id": str(window.get("window_id") or ""),
                "title": title,
                "reason": reason,
            }
        )
    return items


def _load_x11() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")

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
    x11.XStringToKeysym.argtypes = [c_char_p]
    x11.XStringToKeysym.restype = c_ulong
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, c_ulong]
    x11.XKeysymToKeycode.restype = c_uint
    x11.XSync.argtypes = [ctypes.c_void_p, c_int]

    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, c_uint, c_int, c_ulong]
    xtst.XTestFakeKeyEvent.restype = c_int

    return x11, xtst


def _activate_window(
    x11: ctypes.CDLL, display: ctypes.c_void_p, window_id: str
) -> None:
    root = x11.XDefaultRootWindow(display)
    atom = x11.XInternAtom(display, b"_NET_ACTIVE_WINDOW", 0)
    event = XEvent()
    event.xclient.type = CLIENT_MESSAGE
    event.xclient.serial = 0
    event.xclient.send_event = 1
    event.xclient.display = display
    event.xclient.window = int(window_id, 16)
    event.xclient.message_type = atom
    event.xclient.format = 32
    event.xclient.data.l[0] = 1
    event.xclient.data.l[1] = 0
    event.xclient.data.l[2] = 0
    event.xclient.data.l[3] = 0
    event.xclient.data.l[4] = 0
    x11.XSendEvent(
        display,
        root,
        0,
        SUBSTRUCTURE_REDIRECT_MASK | SUBSTRUCTURE_NOTIFY_MASK,
        ctypes.byref(event),
    )
    x11.XFlush(display)


def _send_key_sequence(
    x11: ctypes.CDLL,
    xtst: ctypes.CDLL,
    display: ctypes.c_void_p,
    *keysyms: str,
) -> None:
    keycodes: list[c_uint] = []
    for name in keysyms:
        keysym = x11.XStringToKeysym(name.encode("utf-8"))
        if not keysym:
            raise RuntimeError(f"unknown keysym: {name}")
        keycode = x11.XKeysymToKeycode(display, keysym)
        if not keycode:
            raise RuntimeError(f"unable to map keysym: {name}")
        keycodes.append(keycode)

    for keycode in keycodes:
        xtst.XTestFakeKeyEvent(display, keycode, 1, 0)
    for keycode in reversed(keycodes):
        xtst.XTestFakeKeyEvent(display, keycode, 0, 0)
    x11.XSync(display, 0)


def refresh_windows(
    *,
    hard: bool = False,
    settle_ms: int = DEFAULT_SETTLE_MS,
    between_ms: int = DEFAULT_BETWEEN_MS,
) -> dict[str, object]:
    windows = candidate_windows()
    _, active_window = parse_root_windows()
    if not windows:
        return {"active_window": active_window, "refreshed": []}

    x11, xtst = _load_x11()
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Unable to open X display")

    refreshed: list[dict[str, str]] = []
    try:
        for item in windows:
            window_id = str(item["window_id"])
            _activate_window(x11, display, window_id)
            time.sleep(max(settle_ms, 0) / 1000.0)
            if hard:
                _send_key_sequence(x11, xtst, display, "Control_L", "Shift_L", "r")
            else:
                _send_key_sequence(x11, xtst, display, "F5")
            refreshed.append(item)
            time.sleep(max(between_ms, 0) / 1000.0)
        if active_window:
            _activate_window(x11, display, active_window)
            time.sleep(max(settle_ms, 0) / 1000.0)
    finally:
        x11.XCloseDisplay(display)

    return {"active_window": active_window, "refreshed": refreshed}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh selected dashboard-like Chrome windows on hal."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List windows that would refresh.")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    once_parser = subparsers.add_parser("once", help="Refresh matching windows once.")
    once_parser.add_argument(
        "--hard",
        action="store_true",
        help="Use Ctrl+Shift+R instead of F5.",
    )
    once_parser.add_argument(
        "--settle-ms",
        type=int,
        default=DEFAULT_SETTLE_MS,
        help="Delay after focusing a window before sending refresh keys.",
    )
    once_parser.add_argument(
        "--between-ms",
        type=int,
        default=DEFAULT_BETWEEN_MS,
        help="Delay between refreshing windows.",
    )

    daemon_parser = subparsers.add_parser(
        "daemon", help="Refresh matching windows continuously on an interval."
    )
    daemon_parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between refresh cycles.",
    )
    daemon_parser.add_argument("--hard", action="store_true")
    daemon_parser.add_argument("--settle-ms", type=int, default=DEFAULT_SETTLE_MS)
    daemon_parser.add_argument("--between-ms", type=int, default=DEFAULT_BETWEEN_MS)

    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.command == "list":
        items = candidate_windows()
        if args.json:
            print(json.dumps(items, indent=2))
        else:
            for item in items:
                print(f'{item["window_id"]} [{item["reason"]}] {item["title"]}')
        return 0
    if args.command == "once":
        print(
            json.dumps(
                refresh_windows(
                    hard=bool(args.hard),
                    settle_ms=int(args.settle_ms),
                    between_ms=int(args.between_ms),
                ),
                indent=2,
            )
        )
        return 0
    if args.command == "daemon":
        try:
            while True:
                print(
                    json.dumps(
                        refresh_windows(
                            hard=bool(args.hard),
                            settle_ms=int(args.settle_ms),
                            between_ms=int(args.between_ms),
                        )
                    ),
                    flush=True,
                )
                time.sleep(max(int(args.interval), 1))
        except KeyboardInterrupt:
            return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
