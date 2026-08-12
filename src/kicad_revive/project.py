"""Generating the modern project files: ``sym-lib-table`` and ``.kicad_pro``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .legacy import LegacyProject
from .sexpr import quote


@dataclass
class LibraryEntry:
    nickname: str
    uri: str
    description: str = ""


def write_sym_lib_table(path: Path, entries: list[LibraryEntry]) -> None:
    """Write a project symbol library table.

    Worth generating rather than leaving to the user: upstream KiCad project
    templates routinely ``.gitignore`` ``sym-lib-table``, so a project cloned
    from git often has project-local symbol libraries that resolve to nothing.
    That failure is easy to mistake for a conversion bug, because the symbols
    simply do not draw.
    """
    lines = ["(sym_lib_table", "  (version 7)"]
    for entry in entries:
        lines.append(
            f'  (lib (name "{quote(entry.nickname)}")(type "KiCad")'
            f'(uri "{quote(entry.uri)}")(options "")'
            f'(descr "{quote(entry.description)}"))'
        )
    lines.append(")")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_project_file(
    path: Path,
    *,
    sheets: list[tuple[str, str]],
    legacy: Optional[LegacyProject] = None,
) -> list[str]:
    """Write a ``.kicad_pro``, returning notes about anything not carried over.

    Deliberately minimal.  Nearly everything a legacy ``.pro`` holds --
    netclasses and their net assignments, track and via minimums, mask
    clearances, plot parameters -- is also stored inside the ``.kicad_pcb``'s
    ``(setup)`` and ``(net_class)`` blocks, and modern KiCad loads it from
    there.  Re-encoding it here would risk contradicting the board.
    """
    document = {
        "board": {},
        "boards": [],
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": path.name, "version": 3},
        "net_settings": {},
        "pcbnew": {},
        "schematic": {},
        "sheets": [list(sheet) for sheet in sheets],
        "text_variables": {},
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    notes: list[str] = []
    if legacy is not None:
        orphans = legacy.board_only_settings
        if orphans:
            notes.append(
                "legacy .pro settings with no board equivalent, review in "
                "Board Setup if you relied on them: "
                + ", ".join(f"{k}={v}" for k, v in sorted(orphans.items()))
            )
    return notes


def discover_project_libraries(project_dir: Path) -> list[Path]:
    """Find project-local legacy ``.lib`` symbol libraries.

    Excludes the ``<project>-cache.lib``, which is handled separately: it is a
    snapshot of symbols already in use, not a library to link against.
    """
    found: list[Path] = []
    for candidate in sorted(project_dir.rglob("*.lib")):
        if candidate.stem.endswith("-cache") or candidate.stem.endswith("-rescue"):
            continue
        found.append(candidate)
    return found
