"""Minimal s-expression helpers.

Only what this package needs: locating balanced blocks inside a KiCad file,
quoting/unquoting atoms, and building indented output.  A full parser is
deliberately avoided -- KiCad's files are large, and for extracting symbol
definitions or netlist nodes a scanner is both faster and lossless (it
preserves the original formatting of blocks that are copied through).
"""

from __future__ import annotations

import re
from collections.abc import Iterator


def quote(s: str) -> str:
    r"""Escape a Python string for use as a quoted s-expression atom.

    Newlines and tabs *must* be escaped.  KiCad accepts ``\n`` inside a quoted
    string but rejects a literal newline, and the resulting parse error names
    only the file, not the offending line -- so an unescaped newline in one
    label makes the whole schematic unopenable with no usable diagnostic.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def find_blocks(text: str, head: str, *, depth: int | None = None) -> Iterator[str]:
    """Yield each balanced ``(...)`` block in *text* that starts with *head*.

    *head* is matched literally, e.g. ``"(symbol "`` or ``"(net\\n"``.  When
    *depth* is given, only blocks at that nesting depth are yielded (depth 1 is
    a direct child of the file's root form).  Quoted strings and backslash
    escapes are honoured, so parentheses inside atoms do not confuse it.
    """
    for match in re.finditer(re.escape(head), text):
        start = match.start()
        if depth is not None and _depth_at(text, start) != depth:
            continue
        end = _match_paren(text, start)
        if end is not None:
            yield text[start:end]


def find_blocks_with_indent(text: str, head: str, *, depth: int | None = None) -> Iterator[str]:
    """Like :func:`find_blocks`, but keeps each block's leading indentation.

    Needed when a block is going to be re-indented into a different nesting
    level: without the original indent there is no baseline to shift from.
    """
    for match in re.finditer(re.escape(head), text):
        start = match.start()
        if depth is not None and _depth_at(text, start) != depth:
            continue
        end = _match_paren(text, start)
        if end is None:
            continue
        line_start = text.rfind("\n", 0, start) + 1
        if not text[line_start:start].strip():
            start = line_start
        yield text[start:end]


def find_blocks_matching(
    text: str, pattern: re.Pattern[str], *, depth: int | None = None
) -> Iterator[str]:
    """Like :func:`find_blocks`, but the head is a regular expression.

    Needed where KiCad's own formatting varies between releases -- a literal
    head such as ``"(net\n"`` silently matches nothing against a compact file.
    """
    for match in pattern.finditer(text):
        start = match.start()
        if depth is not None and _depth_at(text, start) != depth:
            continue
        end = _match_paren(text, start)
        if end is not None:
            yield text[start:end]


def _depth_at(text: str, index: int) -> int:
    """Paren nesting depth at *index*, ignoring parens inside quoted atoms."""
    depth = 0
    in_string = False
    escaped = False
    for ch in text[:index]:
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
    return depth


def _match_paren(text: str, start: int) -> int | None:
    """Index just past the ``)`` closing the ``(`` at or after *start*."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
    return None


def reindent(block: str, level: int, *, tab: str = "\t") -> str:
    """Shift a tab-indented *block* so its first line sits at *level*."""
    lines = block.splitlines()
    if not lines:
        return ""
    base = len(lines[0]) - len(lines[0].lstrip(tab))
    out = []
    for line in lines:
        current = len(line) - len(line.lstrip(tab))
        out.append(tab * max(level + current - base, 0) + line.lstrip(tab))
    return "\n".join(out)


class Writer:
    """Accumulates tab-indented s-expression lines."""

    __slots__ = ("_level", "_lines")

    def __init__(self, level: int = 0) -> None:
        self._lines: list[str] = []
        self._level = level

    def line(self, text: str, level: int | None = None) -> None:
        self._lines.append("\t" * (self._level if level is None else level) + text)

    def raw(self, text: str) -> None:
        """Append pre-indented text verbatim (used for copied symbol bodies)."""
        self._lines.append(text)

    def extend(self, lines: list[str]) -> None:
        self._lines.extend(lines)

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"
