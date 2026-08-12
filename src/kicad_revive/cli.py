"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from . import __version__, kicad_cli
from .emit import DEFAULT_FORMAT_VERSION, emit_schematic
from .errors import KicadReviveError
from .report import Style, render_comparison, render_rescue
from .rescue import collect_sheets, rescue_project
from .symbols import build_lib_symbols
from .verify import compare

EPILOG = """\
examples:
  kicad-revive rescue ./myproject
  kicad-revive rescue ./myproject --out-dir ./myproject-modern --overwrite
  kicad-revive convert myproject.sch --cache myproject-cache.kicad_sym
  kicad-revive verify myproject.kicad_sch myproject.kicad_pcb
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kicad-revive",
        description=(
            "Bring a legacy KiCad project forward to the modern file format, "
            "and verify the result against the board it was laid out from."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"kicad-revive {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--kicad-cli", help="path to kicad-cli (default: auto-detect)")

    rescue = subparsers.add_parser(
        "rescue",
        parents=[common],
        help="convert and verify a whole project directory",
        description="Convert every legacy file in a project, then verify it against the board.",
    )
    rescue.add_argument("project", type=Path, help="project directory")
    rescue.add_argument("--out-dir", type=Path, help="write to a copy instead of in place")
    rescue.add_argument("--project-name", help="override the project name")
    rescue.add_argument(
        "--format-version",
        default=None,
        help="kicad_sch format version (default: match the detected kicad-cli)",
    )
    rescue.add_argument("--no-images", action="store_true", help="drop embedded bitmaps")
    rescue.add_argument("--no-verify", action="store_true", help="skip board verification")
    rescue.add_argument(
        "--no-archive",
        action="store_true",
        help="leave legacy sources in place instead of moving them to legacy/",
    )
    rescue.add_argument("--overwrite", action="store_true", help="replace existing output")
    rescue.set_defaults(func=_cmd_rescue)

    convert = subparsers.add_parser(
        "convert",
        parents=[common],
        help="convert a single schematic and its sub-sheets",
        description="Convert one legacy .sch (and any sub-sheets) to .kicad_sch.",
    )
    convert.add_argument("schematic", type=Path, help="root legacy .sch file")
    convert.add_argument(
        "--cache",
        type=Path,
        help="cache library as .kicad_sym; if omitted, the legacy "
        "<project>-cache.lib beside the schematic is converted automatically",
    )
    convert.add_argument("--out-dir", type=Path, help="output directory")
    convert.add_argument("--project-name", help="project name used in instance paths")
    convert.add_argument(
        "--format-version",
        default=DEFAULT_FORMAT_VERSION,
        help=f"kicad_sch format version (default: {DEFAULT_FORMAT_VERSION})",
    )
    convert.add_argument("--no-images", action="store_true")
    convert.add_argument("--overwrite", action="store_true")
    convert.set_defaults(func=_cmd_convert)

    verify = subparsers.add_parser(
        "verify",
        parents=[common],
        help="check a schematic's netlist against a board",
        description=(
            "Compare a schematic's connectivity against a .kicad_pcb. Works on any "
            "KiCad project, not only converted ones."
        ),
    )
    verify.add_argument("schematic", type=Path, help=".kicad_sch to check")
    verify.add_argument("board", type=Path, help=".kicad_pcb to check against")
    verify.set_defaults(func=_cmd_verify)

    return parser


def _cmd_rescue(args: argparse.Namespace) -> int:
    result = rescue_project(
        args.project,
        cli_path=args.kicad_cli,
        out_dir=args.out_dir,
        project_name=args.project_name,
        format_version=args.format_version,
        include_images=not args.no_images,
        archive=not args.no_archive,
        verify=not args.no_verify,
        overwrite=args.overwrite,
    )
    print(render_rescue(result))
    if result.comparison is not None and not result.comparison.nets_ok:
        return 2
    return 0


def _cmd_convert(args: argparse.Namespace) -> int:
    root = Path(args.schematic).resolve()
    name = args.project_name or root.stem
    out_dir = Path(args.out_dir).resolve() if args.out_dir else root.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    sheets, warnings = collect_sheets(root, name)

    cache = args.cache
    if cache is None:
        legacy_cache = next(iter(sorted(root.parent.glob("*-cache.lib"))), None)
        if legacy_cache is not None:
            cli = kicad_cli.find_kicad_cli(args.kicad_cli)
            cache = legacy_cache.with_suffix(".kicad_sym")
            kicad_cli.upgrade_symbol_library(cli, legacy_cache, cache)

    lib_ids: set[str] = set()
    for sheet in sheets:
        lib_ids |= sheet.schematic.lib_ids

    lib_blocks: list[str] = []
    if cache is not None:
        lib_blocks = build_lib_symbols(Path(cache), lib_ids, warnings)
    else:
        warnings.append("no cache library given; symbols will not be embedded")

    for sheet in sheets:
        destination = out_dir / (sheet.source.stem + ".kicad_sch")
        if destination.exists() and not args.overwrite:
            raise KicadReviveError(f"{destination} exists; pass --overwrite")
        destination.write_text(
            emit_schematic(
                sheet.schematic,
                sheet.context,
                lib_blocks=lib_blocks,
                format_version=args.format_version,
                include_images=not args.no_images,
            ),
            encoding="utf-8",
            newline="\n",
        )
        schematic = sheet.schematic
        print(
            f"wrote {destination.name}  "
            f"({len(schematic.components)} symbols, {len(schematic.wires)} wires, "
            f"{len(schematic.texts)} labels, {len(schematic.sheets)} sub-sheets)"
        )
        warnings.extend(f"{sheet.source.name}: {w}" for w in schematic.warnings)

    print(f"{len(lib_ids)} distinct symbols referenced")
    _print_warnings(warnings)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    import tempfile

    cli = kicad_cli.find_kicad_cli(args.kicad_cli)
    schematic = Path(args.schematic).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        netlist = Path(tmp) / "check.net"
        kicad_cli.export_netlist(cli, schematic, netlist)
        comparison = compare(netlist, Path(args.board).resolve())

    style = Style()
    print("")
    for line in render_comparison(comparison, style):
        print(line)
    print("")
    if comparison.nets_ok:
        print(f"  {style.green('PASS')}")
        print("")
        return 0
    print(f"  {style.red('FAIL')}")
    print("")
    return 2


def _print_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    print(f"\n{len(warnings)} warning(s):", file=sys.stderr)
    for warning in warnings:
        print(f"  ! {warning}", file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KicadReviveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
