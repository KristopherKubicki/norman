#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


class PatchError(RuntimeError):
    pass


def _read_patch() -> list[str]:
    lines = sys.stdin.read().splitlines()
    if not lines or lines[0] != "*** Begin Patch":
        raise PatchError("patch must start with *** Begin Patch")
    if lines[-1] != "*** End Patch":
        raise PatchError("patch must end with *** End Patch")
    return lines[1:-1]


def _find_block(haystack: list[str], needle: list[str], start: int = 0) -> int:
    if not needle:
        return max(0, min(start, len(haystack)))
    for index in range(max(0, start), len(haystack) - len(needle) + 1):
        if haystack[index : index + len(needle)] == needle:
            return index
    for index in range(0, len(haystack) - len(needle) + 1):
        if haystack[index : index + len(needle)] == needle:
            return index
    raise PatchError("update hunk context was not found")


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _add_file(path: Path, body: list[str]) -> None:
    if path.exists():
        raise PatchError(f"file already exists: {path}")
    output: list[str] = []
    for line in body:
        if not line.startswith("+"):
            raise PatchError(f"add file lines must start with '+': {path}")
        output.append(line[1:])
    _write_lines(path, output)


def _delete_file(path: Path) -> None:
    if not path.exists():
        raise PatchError(f"file does not exist: {path}")
    path.unlink()


def _apply_update(path: Path, body: list[str]) -> None:
    if not path.exists():
        raise PatchError(f"file does not exist: {path}")
    move_to: Path | None = None
    if body and body[0].startswith("*** Move to: "):
        move_to = Path(body.pop(0).removeprefix("*** Move to: ").strip())

    current = path.read_text(encoding="utf-8").splitlines()
    cursor = 0
    index = 0
    while index < len(body):
        line = body[index]
        if line.startswith("*** End of File"):
            index += 1
            continue
        if not line.startswith("@@"):
            raise PatchError(f"expected update hunk for {path}: {line}")
        index += 1
        old: list[str] = []
        new: list[str] = []
        while index < len(body) and not body[index].startswith("@@"):
            hunk_line = body[index]
            index += 1
            if hunk_line.startswith("*** End of File"):
                break
            if not hunk_line:
                raise PatchError("empty hunk line is missing a prefix")
            prefix = hunk_line[0]
            text = hunk_line[1:]
            if prefix == " ":
                old.append(text)
                new.append(text)
            elif prefix == "-":
                old.append(text)
            elif prefix == "+":
                new.append(text)
            else:
                raise PatchError(f"unknown hunk prefix {prefix!r} in {path}")
        match = _find_block(current, old, cursor)
        current[match : match + len(old)] = new
        cursor = match + len(new)

    target = move_to or path
    _write_lines(target, current)
    if move_to and move_to != path:
        path.unlink()


def apply_patch(lines: list[str]) -> None:
    index = 0
    while index < len(lines):
        header = lines[index]
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("*** "):
            body.append(lines[index])
            index += 1
        if header.startswith("*** Add File: "):
            _add_file(Path(header.removeprefix("*** Add File: ").strip()), body)
        elif header.startswith("*** Delete File: "):
            if body:
                raise PatchError("delete file section must not have a body")
            _delete_file(Path(header.removeprefix("*** Delete File: ").strip()))
        elif header.startswith("*** Update File: "):
            _apply_update(Path(header.removeprefix("*** Update File: ").strip()), body)
        else:
            raise PatchError(f"unknown patch section: {header}")


def main() -> int:
    try:
        apply_patch(_read_patch())
    except PatchError as exc:
        print(f"apply_patch: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
