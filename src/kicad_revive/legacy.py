"""Readers for the legacy KiCad file formats.

Covers the EESchema schematic (``.sch``, "EESchema Schematic File Version"
1 through 4) and the legacy project file (``.pro``).

Format reference:
https://dev-docs.kicad.org/en/file-formats/legacy-4-to-6/legacy_file_format_documentation.pdf
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .errors import NotLegacyFormat

MAGIC = "EESchema Schematic File Version"


# --------------------------------------------------------------------------
# tokenising
# --------------------------------------------------------------------------

def tokenize(line: str) -> list[str]:
    """Split a legacy record into tokens, honouring double-quoted strings."""
    tokens: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if line[i].isspace():
            i += 1
            continue
        if line[i] == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                if line[i] == "\\" and i + 1 < n:
                    buf.append(line[i : i + 2])
                    i += 2
                    continue
                if line[i] == '"':
                    i += 1
                    break
                buf.append(line[i])
                i += 1
            tokens.append("".join(buf))
        else:
            j = i
            while j < n and not line[j].isspace():
                j += 1
            tokens.append(line[i:j])
            i = j
    return tokens


def _at(tokens: list[str], index: int, default: Optional[str] = None) -> Optional[str]:
    return tokens[index] if index < len(tokens) else default


def unescape(text: str) -> str:
    r"""Decode legacy escapes: ``\n`` for newline, ``\\`` for backslash."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------

@dataclass
class Field:
    number: int
    text: str
    orient: str = "H"
    x: str = "0"
    y: str = "0"
    size: str = "50"
    hidden: bool = False
    hjustify: str = "C"
    vjustify: str = "C"
    italic: bool = False
    bold: bool = False
    name: Optional[str] = None


@dataclass
class Component:
    lib_id: str = ""
    ref: str = ""
    unit: int = 1
    convert: int = 1
    stamp: str = ""
    x: str = "0"
    y: str = "0"
    matrix: tuple[int, int, int, int] = (1, 0, 0, -1)
    fields: list[Field] = field(default_factory=list)
    instances: list[dict[str, str]] = field(default_factory=list)


@dataclass
class SheetPin:
    name: str
    form: str
    side: str
    x: str
    y: str
    size: str
    index: str


@dataclass
class Sheet:
    x: str = "0"
    y: str = "0"
    w: str = "0"
    h: str = "0"
    stamp: str = ""
    name: str = ""
    filename: str = ""
    pins: list[SheetPin] = field(default_factory=list)


@dataclass
class Text:
    kind: str
    x: str
    y: str
    orient: int
    size: str
    shape: Optional[str]
    italic: bool
    thickness: str
    text: str


@dataclass
class Bitmap:
    x: str
    y: str
    scale: str
    data: bytes


@dataclass
class Segment:
    kind: str
    x1: str
    y1: str
    x2: str
    y2: str


@dataclass
class Schematic:
    """One parsed legacy sheet."""

    path: Optional[Path] = None
    version: int = 4
    paper: str = "A4"
    paper_w: Optional[str] = None
    paper_h: Optional[str] = None
    portrait: bool = False
    title: str = ""
    date: str = ""
    rev: str = ""
    company: str = ""
    comments: dict[int, str] = field(default_factory=dict)
    page_number: str = "1"
    components: list[Component] = field(default_factory=list)
    wires: list[Segment] = field(default_factory=list)
    entries: list[Segment] = field(default_factory=list)
    junctions: list[tuple[str, str]] = field(default_factory=list)
    noconns: list[tuple[str, str]] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)
    sheets: list[Sheet] = field(default_factory=list)
    bitmaps: list[Bitmap] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def lib_ids(self) -> set[str]:
        return {c.lib_id for c in self.components if c.lib_id}


# --------------------------------------------------------------------------
# schematic parser
# --------------------------------------------------------------------------

def is_legacy_schematic(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.readline().startswith(MAGIC)
    except OSError:
        return False


def parse_schematic(path: Path) -> Schematic:
    """Parse a legacy ``.sch`` file."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or not lines[0].startswith(MAGIC):
        raise NotLegacyFormat(f"{path}: not a legacy EESchema schematic")

    sch = Schematic(path=Path(path))
    match = re.search(r"Version (\d+)", lines[0])
    if match:
        sch.version = int(match.group(1))

    i, n = 1, len(lines)
    while i < n:
        stripped = lines[i].strip()
        i += 1
        if not stripped:
            continue
        if stripped.startswith(("LIBS:", "EELAYER")):
            continue
        if stripped == "$EndSCHEMATC":
            break

        if stripped.startswith("$Descr"):
            i = _parse_descr(sch, lines, i, stripped)
        elif stripped == "$Comp":
            i = _parse_component(sch, lines, i)
        elif stripped == "$Sheet":
            i = _parse_sheet(sch, lines, i)
        elif stripped == "$Bitmap":
            i = _parse_bitmap(sch, lines, i)
        elif stripped.startswith(("Wire ", "Entry ")):
            i = _parse_segment(sch, lines, i, stripped)
        elif stripped.startswith("Connection"):
            tokens = tokenize(stripped)
            sch.junctions.append((_at(tokens, 2, "0") or "0", _at(tokens, 3, "0") or "0"))
        elif stripped.startswith("NoConn"):
            tokens = tokenize(stripped)
            sch.noconns.append((_at(tokens, 2, "0") or "0", _at(tokens, 3, "0") or "0"))
        elif stripped.startswith("Text "):
            i = _parse_text(sch, lines, i, stripped)
        elif stripped.startswith("Kmarq"):
            continue  # obsolete ERC marker; intentionally dropped
        else:
            sch.warnings.append(f"unhandled record: {stripped[:70]}")

    return sch


def _parse_descr(sch: Schematic, lines: list[str], i: int, header: str) -> int:
    tokens = tokenize(header)
    sch.paper = _at(tokens, 1, "A4") or "A4"
    sch.paper_w = _at(tokens, 2)
    sch.paper_h = _at(tokens, 3)
    sch.portrait = "portrait" in header
    while i < len(lines) and lines[i].strip() != "$EndDescr":
        tokens = tokenize(lines[i].strip())
        key = _at(tokens, 0, "") or ""
        value = _at(tokens, 1, "") or ""
        if key == "Sheet":
            sch.page_number = value or "1"
        elif key == "Title":
            sch.title = value
        elif key == "Date":
            sch.date = value
        elif key == "Rev":
            sch.rev = value
        elif key == "Comp":
            sch.company = value
        elif key.startswith("Comment") and key[len("Comment") :].isdigit():
            sch.comments[int(key[len("Comment") :])] = value
        i += 1
    return i + 1


def _parse_component(sch: Schematic, lines: list[str], i: int) -> int:
    comp = Component()
    while i < len(lines) and lines[i].strip() != "$EndComp":
        raw = lines[i]
        stripped = raw.strip()
        i += 1
        if not stripped:
            continue
        tokens = tokenize(stripped)
        key = _at(tokens, 0, "") or ""

        if key == "L":
            comp.lib_id = _at(tokens, 1, "") or ""
            comp.ref = _at(tokens, 2, "") or ""
        elif key == "U":
            comp.unit = int(_at(tokens, 1, "1") or 1)
            comp.convert = int(_at(tokens, 2, "1") or 1)
            comp.stamp = _at(tokens, 3, "") or ""
        elif key == "P":
            comp.x = _at(tokens, 1, "0") or "0"
            comp.y = _at(tokens, 2, "0") or "0"
        elif key == "AR":
            comp.instances.append(dict(re.findall(r'(\w+)="([^"]*)"', stripped)))
        elif key == "F":
            parsed = _parse_field(tokens)
            if parsed is not None:
                comp.fields.append(parsed)
        else:
            # The two trailing indented lines: a redundant "unit x y" triple,
            # then the orientation matrix (four values, each -1, 0 or 1).
            values = tokens
            if len(values) == 4 and all(
                v.lstrip("-").isdigit() and int(v) in (-1, 0, 1) for v in values
            ):
                comp.matrix = (int(values[0]), int(values[1]), int(values[2]), int(values[3]))
            elif len(values) != 3:
                sch.warnings.append(f"unhandled $Comp line: {stripped[:60]}")

    sch.components.append(comp)
    return i + 1


def _parse_field(tokens: list[str]) -> Optional[Field]:
    # F n "text" orient posx posy size flags hjustify vjustify+italic+bold ["name"]
    if len(tokens) < 9:
        return None
    try:
        number = int(tokens[1])
    except ValueError:
        return None
    flags = _at(tokens, 7, "0000") or "0000"
    try:
        hidden = bool(int(flags, 16) & 1)
    except ValueError:
        hidden = False
    style = _at(tokens, 9, "CNN") or "CNN"
    return Field(
        number=number,
        text=unescape(_at(tokens, 2, "") or ""),
        orient=_at(tokens, 3, "H") or "H",
        x=_at(tokens, 4, "0") or "0",
        y=_at(tokens, 5, "0") or "0",
        size=_at(tokens, 6, "50") or "50",
        hidden=hidden,
        hjustify=_at(tokens, 8, "C") or "C",
        vjustify=style[0] if style else "C",
        italic=len(style) > 1 and style[1] == "I",
        bold=len(style) > 2 and style[2] == "B",
        name=_at(tokens, 10),
    )


def _parse_sheet(sch: Schematic, lines: list[str], i: int) -> int:
    sheet = Sheet()
    while i < len(lines) and lines[i].strip() != "$EndSheet":
        stripped = lines[i].strip()
        i += 1
        if not stripped:
            continue
        tokens = tokenize(stripped)
        key = _at(tokens, 0, "") or ""
        if key == "S":
            sheet.x, sheet.y = tokens[1], tokens[2]
            sheet.w, sheet.h = tokens[3], tokens[4]
        elif key == "U":
            sheet.stamp = _at(tokens, 1, "") or ""
        elif key == "F0":
            sheet.name = _at(tokens, 1, "") or ""
        elif key == "F1":
            sheet.filename = _at(tokens, 1, "") or ""
        elif re.fullmatch(r"F\d+", key):
            sheet.pins.append(
                SheetPin(
                    name=_at(tokens, 1, "") or "",
                    form=_at(tokens, 2, "U") or "U",
                    side=_at(tokens, 3, "L") or "L",
                    x=_at(tokens, 4, "0") or "0",
                    y=_at(tokens, 5, "0") or "0",
                    size=_at(tokens, 6, "50") or "50",
                    index=key,
                )
            )
        else:
            sch.warnings.append(f"unhandled $Sheet line: {stripped[:60]}")
    sch.sheets.append(sheet)
    return i + 1


def _parse_bitmap(sch: Schematic, lines: list[str], i: int) -> int:
    x = y = "0"
    scale = "1.0"
    hex_bytes: list[str] = []
    in_data = False
    while i < len(lines) and lines[i].strip() != "$EndBitmap":
        stripped = lines[i].strip()
        i += 1
        if stripped == "Data":
            in_data = True
            continue
        if stripped == "EndData":
            in_data = False
            continue
        if in_data:
            hex_bytes.extend(stripped.split())
            continue
        tokens = tokenize(stripped)
        key = _at(tokens, 0, "") or ""
        if key == "Pos":
            x, y = tokens[1], tokens[2]
        elif key == "Scale":
            # Locale-dependent: some files use a decimal comma.
            scale = (_at(tokens, 1, "1.0") or "1.0").replace(",", ".")
    try:
        data = bytes(int(b, 16) for b in hex_bytes)
    except ValueError:
        sch.warnings.append("bitmap data could not be decoded; image dropped")
        return i + 1
    sch.bitmaps.append(Bitmap(x=x, y=y, scale=scale, data=data))
    return i + 1


def _parse_segment(sch: Schematic, lines: list[str], i: int, header: str) -> int:
    tokens = tokenize(header)
    kind = f"{_at(tokens, 1, '')} {_at(tokens, 2, '')}"
    if i >= len(lines):
        return i
    coords = tokenize(lines[i].strip())
    i += 1
    if len(coords) >= 4:
        segment = Segment(kind, coords[0], coords[1], coords[2], coords[3])
        if header.startswith("Wire "):
            sch.wires.append(segment)
        else:
            sch.entries.append(segment)
    return i


def _parse_text(sch: Schematic, lines: list[str], i: int, header: str) -> int:
    tokens = tokenize(header)
    kind = _at(tokens, 1, "") or ""
    index = 6
    shape = None
    if kind in ("GLabel", "HLabel"):
        shape = _at(tokens, index, "UnSpc")
        index += 1
    style = _at(tokens, index, "~") or "~"
    body = ""
    if i < len(lines):
        body = unescape(lines[i])
        i += 1
    sch.texts.append(
        Text(
            kind=kind,
            x=_at(tokens, 2, "0") or "0",
            y=_at(tokens, 3, "0") or "0",
            orient=int(_at(tokens, 4, "0") or 0),
            size=_at(tokens, 5, "50") or "50",
            shape=shape,
            italic=style == "Italic",
            thickness=_at(tokens, index + 1, "0") or "0",
            text=body,
        )
    )
    return i


# --------------------------------------------------------------------------
# legacy project file
# --------------------------------------------------------------------------

@dataclass
class LegacyProject:
    """The handful of settings a legacy ``.pro`` holds that a board does not.

    Almost everything in a legacy ``.pro`` -- netclasses, track and via
    minimums, mask clearances, plot parameters -- is duplicated inside the
    ``.kicad_pcb``'s own ``(setup)`` and ``(net_class)`` blocks, and modern
    KiCad reads it from there.  Only these few are board-file orphans.
    """

    sections: dict[str, dict[str, str]] = field(default_factory=dict)

    def get(self, section: str, key: str, default: str = "") -> str:
        return self.sections.get(section, {}).get(key, default)

    @property
    def board_only_settings(self) -> dict[str, str]:
        pcb = self.sections.get("pcbnew", {})
        return {k: v for k, v in pcb.items() if k in _PRO_ONLY_KEYS}


_PRO_ONLY_KEYS = {
    "MinHoleToHole",
    "RequireCourtyardDefinitions",
    "ProhibitOverlappingCourtyards",
    "AllowBlindVias",
    "AllowMicroVias",
}


def parse_project(path: Path) -> LegacyProject:
    """Parse a legacy ``.pro`` file (an INI-like key/value format)."""
    project = LegacyProject()
    section = "general"
    project.sections[section] = {}
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            project.sections.setdefault(section, {})
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            project.sections.setdefault(section, {})[key.strip()] = value.strip()
    return project
