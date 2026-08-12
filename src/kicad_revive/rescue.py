"""End-to-end rescue of a legacy KiCad project."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import kicad_cli
from .emit import DEFAULT_FORMAT_VERSION, SheetContext, emit_schematic, stable_uuid, timestamp_uuid
from .errors import OutputExists
from .legacy import Schematic, is_legacy_schematic, parse_project, parse_schematic
from .project import (
    LibraryEntry,
    discover_project_libraries,
    write_project_file,
    write_sym_lib_table,
)
from .symbols import build_lib_symbols
from .verify import Comparison, compare


@dataclass
class ConvertedSheet:
    source: Path
    destination: Path
    schematic: Schematic
    context: SheetContext


@dataclass
class RescueResult:
    project_dir: Path
    project_name: str
    sheets: list[ConvertedSheet] = field(default_factory=list)
    symbol_count: int = 0
    converted_libraries: list[Path] = field(default_factory=list)
    cache_library: Optional[Path] = None
    sym_lib_table: Optional[Path] = None
    project_file: Optional[Path] = None
    board: Optional[Path] = None
    board_version: Optional[str] = None
    format_version: Optional[str] = None
    archived_to: Optional[Path] = None
    comparison: Optional[Comparison] = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_components(self) -> int:
        return sum(len(s.schematic.components) for s in self.sheets)


def find_root_schematic(project_dir: Path) -> Optional[Path]:
    """Pick the root sheet: the one no other sheet references as a sub-sheet."""
    candidates = [p for p in sorted(project_dir.glob("*.sch")) if is_legacy_schematic(p)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    referenced: set[str] = set()
    for path in candidates:
        try:
            for sheet in parse_schematic(path).sheets:
                referenced.add(sheet.filename)
        except Exception:
            continue

    roots = [p for p in candidates if p.name not in referenced]
    if len(roots) == 1:
        return roots[0]

    # Ambiguous: prefer one named after the directory or an adjacent project file.
    for path in roots or candidates:
        if path.stem == project_dir.name:
            return path
    pro = sorted(project_dir.glob("*.pro"))
    if pro:
        for path in roots or candidates:
            if path.stem == pro[0].stem:
                return path
    return (roots or candidates)[0]


def collect_sheets(root: Path, project_name: str) -> tuple[list[ConvertedSheet], list[str]]:
    """Walk the sheet hierarchy from *root*, parsing every sheet once."""
    root_uuid = stable_uuid("root", project_name)
    queue: list[tuple[Path, str, str]] = [(root, "/" + root_uuid, root_uuid)]
    seen: set[Path] = set()
    sheets: list[ConvertedSheet] = []
    warnings: list[str] = []

    while queue:
        path, sheet_path, sheet_uuid = queue.pop(0)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.exists():
            warnings.append(f"referenced sheet not found: {path.name}")
            continue

        schematic = parse_schematic(path)
        context = SheetContext(
            project_name=project_name,
            root_uuid=root_uuid,
            sheet_path=sheet_path,
            sheet_uuid=sheet_uuid,
        )
        sheets.append(
            ConvertedSheet(
                source=path,
                destination=path.with_suffix(".kicad_sch"),
                schematic=schematic,
                context=context,
            )
        )
        for child in schematic.sheets:
            child_path = path.parent / child.filename
            child_uuid = (
                timestamp_uuid(child.stamp)
                if child.stamp
                else stable_uuid(sheet_path, child.filename)
            )
            queue.append(
                (
                    child_path,
                    f"{sheet_path}/{child_uuid}",
                    stable_uuid("sheetfile", child.filename),
                )
            )
    return sheets, warnings


def rescue_project(
    project_dir: Path,
    *,
    cli_path: Optional[str] = None,
    out_dir: Optional[Path] = None,
    project_name: Optional[str] = None,
    format_version: Optional[str] = None,
    include_images: bool = True,
    archive: bool = True,
    verify: bool = True,
    overwrite: bool = False,
) -> RescueResult:
    """Convert an entire legacy project and verify it against its board.

    ``format_version`` defaults to whatever the detected kicad-cli writes, so
    the embedded symbols and the schematic that contains them always target
    the same KiCad.
    """
    project_dir = Path(project_dir).resolve()
    target = Path(out_dir).resolve() if out_dir else project_dir

    root = find_root_schematic(project_dir)
    if root is None:
        from .errors import NotLegacyFormat

        raise NotLegacyFormat(f"no legacy .sch files found in {project_dir}")

    name = project_name or root.stem
    result = RescueResult(project_dir=target, project_name=name)

    if target != project_dir:
        target.mkdir(parents=True, exist_ok=True)
        for item in project_dir.iterdir():
            if item.is_dir():
                shutil.copytree(item, target / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target / item.name)
        root = target / root.name

    cli = kicad_cli.find_kicad_cli(cli_path)
    if format_version is None:
        format_version = kicad_cli.schematic_format_version(cli, DEFAULT_FORMAT_VERSION)
    result.format_version = format_version

    # --- schematics -------------------------------------------------------
    sheets, warnings = collect_sheets(root, name)
    result.sheets = sheets
    result.warnings.extend(warnings)

    if not overwrite:
        for sheet in sheets:
            if sheet.destination.exists():
                raise OutputExists(
                    f"{sheet.destination.name} already exists; pass --overwrite to replace it"
                )

    # --- symbol libraries -------------------------------------------------
    lib_ids: set[str] = set()
    for sheet in sheets:
        lib_ids |= sheet.schematic.lib_ids
    result.symbol_count = len(lib_ids)

    cache = _find_cache_library(target, name)
    if cache is None:
        result.warnings.append(
            "no <project>-cache.lib found; symbol geometry cannot be embedded"
        )
        lib_blocks: list[str] = []
    else:
        converted_cache = cache.with_suffix(".kicad_sym")
        kicad_cli.upgrade_symbol_library(cli, cache, converted_cache)
        result.cache_library = converted_cache
        lib_blocks = build_lib_symbols(converted_cache, lib_ids, result.warnings)

    entries: list[LibraryEntry] = []
    for legacy_lib in discover_project_libraries(target):
        converted = legacy_lib.with_suffix(".kicad_sym")
        kicad_cli.upgrade_symbol_library(cli, legacy_lib, converted)
        result.converted_libraries.append(converted)
        entries.append(
            LibraryEntry(
                nickname=legacy_lib.stem,
                uri="${KIPRJMOD}/" + converted.relative_to(target).as_posix(),
                description=f"converted from {legacy_lib.name}",
            )
        )

    # --- write schematics -------------------------------------------------
    for sheet in sheets:
        text = emit_schematic(
            sheet.schematic,
            sheet.context,
            lib_blocks=lib_blocks,
            format_version=format_version,
            include_images=include_images,
        )
        sheet.destination.write_text(text, encoding="utf-8", newline="\n")
        result.warnings.extend(
            f"{sheet.source.name}: {w}" for w in sheet.schematic.warnings
        )

    # --- project files ----------------------------------------------------
    if entries:
        table = target / "sym-lib-table"
        write_sym_lib_table(table, entries)
        result.sym_lib_table = table

    legacy_pro = next(iter(sorted(target.glob("*.pro"))), None)
    legacy_project = parse_project(legacy_pro) if legacy_pro else None

    sheet_entries = [(sheets[0].context.root_uuid, "Root")]
    for sheet in sheets[1:]:
        sheet_entries.append((sheet.context.sheet_path.rsplit("/", 1)[-1], sheet.source.stem))

    project_file = target / f"{name}.kicad_pro"
    result.notes.extend(
        write_project_file(project_file, sheets=sheet_entries, legacy=legacy_project)
    )
    result.project_file = project_file

    # --- board ------------------------------------------------------------
    board = next(iter(sorted(target.glob("*.kicad_pcb"))), None)
    if board is not None:
        result.board = board
        result.board_version = _board_version(board)

    # --- verification -----------------------------------------------------
    if verify and board is not None:
        netlist = target / f"{name}.revive-check.net"
        try:
            kicad_cli.export_netlist(cli, sheets[0].destination, netlist)
            result.comparison = compare(netlist, board)
        finally:
            netlist.unlink(missing_ok=True)

    # --- archive legacy sources ------------------------------------------
    if archive:
        result.archived_to = _archive_legacy(target, sheets)

    return result


def _find_cache_library(project_dir: Path, name: str) -> Optional[Path]:
    exact = project_dir / f"{name}-cache.lib"
    if exact.exists():
        return exact
    matches = sorted(project_dir.glob("*-cache.lib"))
    return matches[0] if matches else None


def _board_version(board: Path) -> Optional[str]:
    with open(board, encoding="utf-8", errors="replace") as handle:
        head = handle.read(400)
    match = re.search(r"\(version (\d+)\)", head)
    return match.group(1) if match else None


def _archive_legacy(project_dir: Path, sheets: list[ConvertedSheet]) -> Optional[Path]:
    """Move the legacy sources aside so KiCad cannot reopen and re-stub them.

    Kept rather than deleted: they are the only full-fidelity record of the
    original, and the conversion should stay auditable against them.
    """
    archive_dir = project_dir / "legacy"
    moved = False
    archive_dir.mkdir(exist_ok=True)

    for sheet in sheets:
        if sheet.source.exists():
            shutil.move(str(sheet.source), str(archive_dir / sheet.source.name))
            moved = True
    for pattern in ("*.pro", "*-cache.lib", "*-rescue.lib", "*.lib"):
        for item in sorted(project_dir.glob(pattern)):
            shutil.move(str(item), str(archive_dir / item.name))
            moved = True
    for libdir in sorted(project_dir.glob("**/*.lib")):
        if archive_dir not in libdir.parents:
            shutil.move(str(libdir), str(archive_dir / libdir.name))
            moved = True

    if not moved:
        archive_dir.rmdir()
        return None
    return archive_dir
