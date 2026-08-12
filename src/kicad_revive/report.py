"""Console output."""

from __future__ import annotations

import os
import sys
from typing import Optional

from .rescue import RescueResult
from .verify import Comparison


def _supports_colour(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class Style:
    def __init__(self, stream=None) -> None:
        self.enabled = _supports_colour(stream or sys.stdout)

    def _wrap(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def dim(self, text: str) -> str:
        return self._wrap(text, "2")

    def bold(self, text: str) -> str:
        return self._wrap(text, "1")

    def green(self, text: str) -> str:
        return self._wrap(text, "32")

    def yellow(self, text: str) -> str:
        return self._wrap(text, "33")

    def red(self, text: str) -> str:
        return self._wrap(text, "31")


def _row(style: Style, label: str, value: str) -> str:
    return f"  {style.dim(label.ljust(13))} {value}"


def render_rescue(result: RescueResult, style: Optional[Style] = None) -> str:
    style = style or Style()
    out: list[str] = []
    out.append("")
    out.append(f"  {style.bold(result.project_name)}  {style.dim(str(result.project_dir))}")
    out.append("")

    if result.cache_library:
        out.append(
            _row(style, "symbols", f"{result.cache_library.name}  ({result.symbol_count} used)")
        )
    for lib in result.converted_libraries:
        out.append(_row(style, "library", lib.name))

    sheet_names = ", ".join(s.destination.name for s in result.sheets)
    out.append(
        _row(
            style,
            "schematics",
            f"{sheet_names}  ({result.total_components} symbols)",
        )
    )

    if result.sym_lib_table:
        out.append(_row(style, "libraries", "wrote sym-lib-table"))
    if result.project_file:
        out.append(_row(style, "project", f"wrote {result.project_file.name}"))
    if result.board:
        version = result.board_version or "unknown"
        out.append(
            _row(style, "board", f"{result.board.name}  v{version} - readable, left as-is")
        )
    if result.archived_to:
        out.append(_row(style, "archived", f"legacy sources -> {result.archived_to.name}/"))

    if result.comparison is not None:
        out.append("")
        out.extend(render_comparison(result.comparison, style))

    if result.notes:
        out.append("")
        for note in result.notes:
            out.append(f"  {style.dim('note')}  {note}")

    if result.warnings:
        out.append("")
        out.append(f"  {style.yellow(f'{len(result.warnings)} warning(s)')}")
        for warning in result.warnings[:20]:
            out.append(f"    {style.dim('!')} {warning}")
        if len(result.warnings) > 20:
            out.append(f"    {style.dim(f'... and {len(result.warnings) - 20} more')}")

    out.append("")
    if result.comparison is None:
        out.append(f"  {style.yellow('converted')} - no board found, so nothing to verify against")
    elif result.comparison.ok:
        out.append(f"  {style.green('rescued')} - open {result.project_name}.kicad_pro in KiCad")
    elif result.comparison.nets_ok:
        out.append(f"  {style.green('rescued')} - connectivity verified; see notes above")
    else:
        out.append(f"  {style.red('VERIFICATION FAILED')} - do not trust this conversion")
    out.append("")
    return "\n".join(out)


def render_comparison(comparison: Comparison, style: Optional[Style] = None) -> list[str]:
    style = style or Style()
    out = [f"  {style.bold('verify')}  {style.dim('schematic netlist vs. board')}"]

    total = max(comparison.total_schematic_nets, comparison.total_board_nets)
    nets = f"{comparison.matched_nets}/{total} node sets identical"
    out.append(
        _row(style, "nets", style.green(nets) if comparison.nets_ok else style.red(nets))
    )

    refs = f"{len(comparison.schematic_refs & comparison.board_refs)}/{len(comparison.board_refs)} matched"
    out.append(_row(style, "components", refs))

    if comparison.missing_refs:
        listed = ", ".join(sorted(comparison.missing_refs)[:8])
        out.append(
            _row(
                style,
                "board-only",
                style.dim(f"{listed}  (board graphics have no symbol - usually fine)"),
            )
        )
    if comparison.extra_refs:
        listed = ", ".join(sorted(comparison.extra_refs)[:8])
        out.append(_row(style, "not on board", style.yellow(listed)))

    for name, nodes in comparison.schematic_only[:5]:
        out.append(_row(style, "sch-only net", style.red(f"{name}: {sorted(nodes)[:4]}")))
    for name, nodes in comparison.board_only[:5]:
        out.append(_row(style, "board-only net", style.red(f"{name}: {sorted(nodes)[:4]}")))

    return out
