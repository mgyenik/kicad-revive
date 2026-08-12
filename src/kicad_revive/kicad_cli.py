"""Locating and invoking ``kicad-cli``.

Used for two things this package deliberately does not reimplement: converting
legacy ``.lib`` symbol libraries (that importer still works in every KiCad
release) and exporting a netlist from converted output so it can be verified.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .errors import KicadCliNotFound, SymbolLibraryConversionFailed

#: Well-known install locations, newest first.  ``PATH`` is tried before these.
_SEARCH_GLOBS = [
    "C:/Program Files/KiCad/*/bin/kicad-cli.exe",
    "C:/Program Files (x86)/KiCad/*/bin/kicad-cli.exe",
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
    "/snap/bin/kicad-cli",
]


def _version_key(path: Path) -> tuple:
    numbers = [int(n) for n in re.findall(r"\d+", str(path.parent.parent.name))]
    return tuple(numbers) if numbers else (0,)


def find_kicad_cli(explicit: Optional[str] = None) -> Path:
    """Locate ``kicad-cli``, preferring an explicit path, then ``PATH``.

    Falls back to scanning standard install locations and picking the highest
    version found, since a machine may have several KiCad releases side by side.
    """
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
        raise KicadCliNotFound(f"kicad-cli not found at {explicit}")

    env = os.environ.get("KICAD_CLI")
    if env and Path(env).is_file():
        return Path(env)

    on_path = shutil.which("kicad-cli")
    if on_path:
        return Path(on_path)

    matches: list[Path] = []
    for pattern in _SEARCH_GLOBS:
        if "*" in pattern:
            root = Path(pattern.split("*")[0])
            if root.exists():
                matches.extend(p for p in root.parent.glob(Path(pattern).relative_to(root.parent).as_posix()) if p.is_file())
        elif Path(pattern).is_file():
            matches.append(Path(pattern))

    if matches:
        return sorted(matches, key=_version_key)[-1]

    raise KicadCliNotFound(
        "kicad-cli not found. Install KiCad, put kicad-cli on PATH, "
        "set the KICAD_CLI environment variable, or pass --kicad-cli."
    )


def run(cli: Path, args: list[str], *, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Invoke kicad-cli, capturing output."""
    return subprocess.run(
        [str(cli), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def version(cli: Path) -> str:
    result = run(cli, ["version"])
    return (result.stdout or result.stderr).strip().splitlines()[0] if result.stdout or result.stderr else "unknown"


def upgrade_symbol_library(cli: Path, source: Path, destination: Path) -> None:
    """Convert a legacy ``.lib`` symbol library to ``.kicad_sym``.

    The destination is removed first, and success is judged on the file having
    actually been written by *this* run.  Testing only for existence afterwards
    is a trap: a stale ``.kicad_sym`` left by an earlier conversion (or by a
    different KiCad version) makes a failed run look successful, and the
    symbols then embedded in the schematic are in a format the target KiCad may
    refuse -- which surfaces much later as an unhelpful "Failed to load
    schematic".
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    result = run(cli, ["sym", "upgrade", str(source), "-o", str(destination)])

    if result.returncode != 0 or not destination.exists():
        message = (result.stderr or result.stdout).strip() or "no output from kicad-cli"
        hint = ""
        if source.suffix.lower() == ".lib":
            hint = (
                "\n\nkicad-cli from KiCad 7 and earlier cannot read legacy .lib "
                "symbol libraries. Point --kicad-cli at a newer KiCad if you have one."
            )
        raise SymbolLibraryConversionFailed(
            f"failed to convert {source.name}: {message}{hint}"
        )


#: KiCad major version -> the ``.kicad_sch`` format version it writes.
_SCHEMATIC_FORMAT_VERSIONS = {
    6: "20211123",
    7: "20230121",
    8: "20231120",
    9: "20250114",
    10: "20260306",
}


def major_version(cli: Path) -> Optional[int]:
    """Major version of a kicad-cli, or ``None`` if it cannot be determined."""
    match = re.match(r"\s*(\d+)\.", version(cli))
    return int(match.group(1)) if match else None


def schematic_format_version(cli: Path, fallback: str) -> str:
    """Pick the ``.kicad_sch`` format version matching *cli*.

    Symbol geometry is converted by kicad-cli, so the schematic must declare a
    format that the same KiCad understands.  Emitting a fixed version means a
    KiCad 9 user gets KiCad 9 symbols inside a file claiming a format its own
    parser may not accept.
    """
    major = major_version(cli)
    if major is None:
        return fallback
    if major in _SCHEMATIC_FORMAT_VERSIONS:
        return _SCHEMATIC_FORMAT_VERSIONS[major]
    # Newer than anything known: the fallback is the newest version we know of.
    return fallback if major < max(_SCHEMATIC_FORMAT_VERSIONS) else _SCHEMATIC_FORMAT_VERSIONS[
        max(_SCHEMATIC_FORMAT_VERSIONS)
    ]


def export_netlist(cli: Path, schematic: Path, destination: Path) -> Path:
    """Export a KiCad netlist from a schematic."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run(
        cli,
        ["sch", "export", "netlist", "--output", str(destination), str(schematic)],
        cwd=schematic.parent,
    )
    if not destination.exists():
        message = (result.stderr or result.stdout).strip()
        raise KicadCliNotFound(f"failed to export netlist: {message}")
    return destination
