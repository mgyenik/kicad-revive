"""Writer for modern ``.kicad_sch`` files.

Format reference:
https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/index.html
"""

from __future__ import annotations

import base64
import re
import uuid as uuidmod
from dataclasses import dataclass
from typing import Optional

from .geometry import (
    SHAPE_TABLE,
    SHEET_PIN_ANGLE,
    SHEET_PIN_FORM,
    field_angle,
    label_angle,
    label_justify,
    mm,
    orientation,
    transform_field,
)
from .legacy import Component, Schematic, Sheet
from .sexpr import Writer, quote

#: Default output format version.  KiCad 8 and newer read this; older releases
#: do not, but they can open the legacy input directly anyway.
DEFAULT_FORMAT_VERSION = "20250114"

GENERATOR = "kicad-revive"

PROPERTY_NAMES = {0: "Reference", 1: "Value", 2: "Footprint", 3: "Datasheet"}

KNOWN_PAPER = {
    "A0", "A1", "A2", "A3", "A4", "A5",
    "A", "B", "C", "D", "E",
    "USLetter", "USLegal", "USLedger",
}

_UUID_NAMESPACE = uuidmod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def timestamp_uuid(stamp: str) -> str:
    """Convert a legacy 8-hex-digit timestamp to the UUID KiCad derives from it.

    KiCad zero-pads the timestamp into a UUID rather than inventing a random
    one.  Confirmed against KiCad's own output: a sheet stamped ``5F109712``
    appears in an exported netlist as
    ``00000000-0000-0000-0000-00005f109712``.  Reproducing that convention
    keeps hierarchical instance paths stable and comparable.
    """
    cleaned = re.sub(r"[^0-9a-f]", "", stamp.strip().lower())[:12]
    return "00000000-0000-0000-0000-" + cleaned.rjust(12, "0")


def stable_uuid(*parts: str) -> str:
    """Deterministic UUID for objects the legacy format never stamped.

    Derived from content so that converting the same input twice produces
    byte-identical output, which makes conversions reviewable in version
    control and lets the test suite assert determinism.
    """
    return str(uuidmod.uuid5(_UUID_NAMESPACE, "|".join(parts)))


@dataclass
class SheetContext:
    """Where a sheet sits in the hierarchy, for instance paths."""

    project_name: str
    root_uuid: str
    sheet_path: str
    sheet_uuid: str


def effects(
    size_mils: str,
    *,
    hjustify: Optional[str] = None,
    vjustify: Optional[str] = None,
    italic: bool = False,
    bold: bool = False,
    hidden: bool = False,
    indent: int = 3,
) -> list[str]:
    tab = "\t" * indent
    size = mm(size_mils)
    out = [f"{tab}(effects", f"{tab}\t(font", f"{tab}\t\t(size {size} {size})"]
    if bold:
        out.append(f"{tab}\t\t(bold yes)")
    if italic:
        out.append(f"{tab}\t\t(italic yes)")
    out.append(f"{tab}\t)")

    justify = []
    if hjustify == "L":
        justify.append("left")
    elif hjustify == "R":
        justify.append("right")
    if vjustify == "T":
        justify.append("top")
    elif vjustify == "B":
        justify.append("bottom")
    if justify:
        out.append(f"{tab}\t(justify {' '.join(justify)})")
    if hidden:
        out.append(f"{tab}\t(hide yes)")
    out.append(f"{tab})")
    return out


def emit_schematic(
    sch: Schematic,
    context: SheetContext,
    *,
    lib_blocks: list[str],
    format_version: str = DEFAULT_FORMAT_VERSION,
    include_images: bool = True,
) -> str:
    """Render a parsed legacy sheet as a modern ``.kicad_sch`` document."""
    w = Writer()

    w.line("(kicad_sch")
    w.line(f"(version {format_version})", 1)
    w.line(f'(generator "{GENERATOR}")', 1)
    w.line('(generator_version "1.0")', 1)
    w.line(f'(uuid "{context.sheet_uuid}")', 1)
    _emit_paper(w, sch)
    _emit_title_block(w, sch)

    w.line("(lib_symbols", 1)
    for block in lib_blocks:
        w.raw(block)
    w.line(")", 1)

    _emit_segments(w, sch, context)
    _emit_junctions(w, sch, context)
    _emit_noconns(w, sch, context)
    _emit_texts(w, sch, context)
    if include_images:
        _emit_images(w, sch, context)
    for comp in sch.components:
        _emit_component(w, comp, sch, context)
    for sheet in sch.sheets:
        _emit_sheet(w, sheet, context)

    w.line("(sheet_instances", 1)
    w.line('(path "/"', 2)
    w.line(f'(page "{quote(sch.page_number)}")', 3)
    w.line(")", 2)
    w.line(")", 1)
    w.line(")")
    return w.render()


def _emit_paper(w: Writer, sch: Schematic) -> None:
    if sch.paper in KNOWN_PAPER:
        suffix = " portrait)" if sch.portrait else ")"
        w.line(f'(paper "{sch.paper}"{suffix}', 1)
    elif sch.paper_w and sch.paper_h:
        w.line(f'(paper "User" {mm(sch.paper_w)} {mm(sch.paper_h)})', 1)
    else:
        w.line('(paper "A4")', 1)


def _emit_title_block(w: Writer, sch: Schematic) -> None:
    if not any([sch.title, sch.date, sch.rev, sch.company, sch.comments]):
        return
    w.line("(title_block", 1)
    if sch.title:
        w.line(f'(title "{quote(sch.title)}")', 2)
    if sch.date:
        w.line(f'(date "{quote(sch.date)}")', 2)
    if sch.rev:
        w.line(f'(rev "{quote(sch.rev)}")', 2)
    if sch.company:
        w.line(f'(company "{quote(sch.company)}")', 2)
    for number in sorted(sch.comments):
        if sch.comments[number]:
            w.line(f'(comment {number} "{quote(sch.comments[number])}")', 2)
    w.line(")", 1)


def _emit_segments(w: Writer, sch: Schematic, ctx: SheetContext) -> None:
    tags = {"Wire Line": "wire", "Bus Line": "bus", "Notes Line": "polyline"}
    for seg in sch.wires:
        tag = tags.get(seg.kind)
        if tag is None:
            sch.warnings.append(f"unhandled wire kind: {seg.kind}")
            continue
        w.line(f"({tag}", 1)
        w.line("(pts", 2)
        w.line(f"(xy {mm(seg.x1)} {mm(seg.y1)}) (xy {mm(seg.x2)} {mm(seg.y2)})", 3)
        w.line(")", 2)
        w.line("(stroke", 2)
        w.line("(width 0)", 3)
        w.line(f"(type {'dash' if tag == 'polyline' else 'default'})", 3)
        w.line(")", 2)
        uid = stable_uuid(ctx.sheet_uuid, "w", seg.kind, seg.x1, seg.y1, seg.x2, seg.y2)
        w.line(f'(uuid "{uid}")', 2)
        w.line(")", 1)

    for seg in sch.entries:
        w.line("(bus_entry", 1)
        w.line(f"(at {mm(seg.x1)} {mm(seg.y1)})", 2)
        w.line(
            f"(size {mm(float(seg.x2) - float(seg.x1))} "
            f"{mm(float(seg.y2) - float(seg.y1))})",
            2,
        )
        w.line("(stroke", 2)
        w.line("(width 0)", 3)
        w.line("(type default)", 3)
        w.line(")", 2)
        uid = stable_uuid(ctx.sheet_uuid, "e", seg.x1, seg.y1, seg.x2, seg.y2)
        w.line(f'(uuid "{uid}")', 2)
        w.line(")", 1)


def _emit_junctions(w: Writer, sch: Schematic, ctx: SheetContext) -> None:
    for x, y in sch.junctions:
        w.line("(junction", 1)
        w.line(f"(at {mm(x)} {mm(y)})", 2)
        w.line("(diameter 0)", 2)
        w.line("(color 0 0 0 0)", 2)
        w.line(f'(uuid "{stable_uuid(ctx.sheet_uuid, "j", x, y)}")', 2)
        w.line(")", 1)


def _emit_noconns(w: Writer, sch: Schematic, ctx: SheetContext) -> None:
    for x, y in sch.noconns:
        w.line("(no_connect", 1)
        w.line(f"(at {mm(x)} {mm(y)})", 2)
        w.line(f'(uuid "{stable_uuid(ctx.sheet_uuid, "n", x, y)}")', 2)
        w.line(")", 1)


def _emit_texts(w: Writer, sch: Schematic, ctx: SheetContext) -> None:
    tags = {
        "Notes": "text",
        "Label": "label",
        "GLabel": "global_label",
        "HLabel": "hierarchical_label",
    }
    for index, text in enumerate(sch.texts):
        tag = tags.get(text.kind)
        if tag is None:
            sch.warnings.append(f"unhandled text kind: {text.kind}")
            continue

        angle = label_angle(text.kind, text.orient)
        hjustify, vjustify = label_justify(text.kind, angle)

        w.line(f'({tag} "{quote(text.text)}"', 1)
        if tag in ("global_label", "hierarchical_label"):
            w.line(f"(shape {SHAPE_TABLE.get(text.shape or '', 'passive')})", 2)
        if tag == "text":
            w.line("(exclude_from_sim no)", 2)
        w.line(f"(at {mm(text.x)} {mm(text.y)} {angle})", 2)
        w.extend(
            effects(
                text.size,
                hjustify=hjustify,
                vjustify=vjustify,
                italic=text.italic,
                indent=2,
            )
        )
        w.line(f'(uuid "{stable_uuid(ctx.sheet_uuid, "t", str(index), text.text)}")', 2)
        w.line(")", 1)


def _emit_images(w: Writer, sch: Schematic, ctx: SheetContext) -> None:
    for index, bitmap in enumerate(sch.bitmaps):
        w.line("(image", 1)
        w.line(f"(at {mm(bitmap.x)} {mm(bitmap.y)})", 2)
        if abs(float(bitmap.scale) - 1.0) > 1e-9:
            w.line(f"(scale {bitmap.scale})", 2)
        w.line(f'(uuid "{stable_uuid(ctx.sheet_uuid, "img", str(index))}")', 2)
        w.line("(data", 2)
        encoded = base64.b64encode(bitmap.data).decode("ascii")
        for pos in range(0, len(encoded), 76):
            w.line(f'"{encoded[pos:pos + 76]}"', 3)
        w.line(")", 2)
        w.line(")", 1)


def _resolve_instance(comp: Component, ctx: SheetContext) -> tuple[str, int]:
    """Pick this sheet's reference/unit from the legacy ``AR`` records.

    A legacy ``AR`` path ends with the symbol's own timestamp, whereas a modern
    instance path names only the sheets above it -- so the sheet path is
    everything except that final element.
    """
    if not comp.instances:
        return comp.ref, comp.unit

    for entry in comp.instances:
        parts = [p for p in entry.get("Path", "").split("/") if p]
        modern = "/" + "/".join([ctx.root_uuid] + [timestamp_uuid(p) for p in parts[:-1]])
        if modern == ctx.sheet_path:
            return entry.get("Ref", comp.ref), int(entry.get("Part", comp.unit) or comp.unit)

    last = comp.instances[-1]
    return last.get("Ref", comp.ref), int(last.get("Part", comp.unit) or comp.unit)


def _emit_component(w: Writer, comp: Component, sch: Schematic, ctx: SheetContext) -> None:
    try:
        angle, mirror = orientation(comp.matrix)
    except KeyError:
        sch.warnings.append(
            f"{comp.ref}: unrecognised orientation matrix {comp.matrix}; assuming 0 degrees"
        )
        angle, mirror = 0, None

    uid = (
        timestamp_uuid(comp.stamp)
        if comp.stamp
        else stable_uuid(ctx.sheet_path, comp.ref, comp.x, comp.y)
    )
    ref, unit = _resolve_instance(comp, ctx)

    w.line("(symbol", 1)
    w.line(f'(lib_id "{quote(comp.lib_id)}")', 2)
    w.line(f"(at {mm(comp.x)} {mm(comp.y)} {angle})", 2)
    if mirror:
        w.line(f"(mirror {mirror})", 2)
    w.line(f"(unit {unit})", 2)
    w.line("(exclude_from_sim no)", 2)
    w.line("(in_bom yes)", 2)
    w.line("(on_board yes)", 2)
    w.line("(dnp no)", 2)
    w.line(f'(uuid "{uid}")', 2)

    symbol_xy = (float(comp.x), float(comp.y))
    for fld in sorted(comp.fields, key=lambda f: f.number):
        name = PROPERTY_NAMES.get(fld.number) or (fld.name or f"Field{fld.number}")
        value = ref if fld.number == 0 else fld.text
        px, py = transform_field(comp.matrix, symbol_xy, (float(fld.x), float(fld.y)))
        w.line(f'(property "{quote(name)}" "{quote(value)}"', 2)
        w.line(f"(at {mm(px)} {mm(py)} {field_angle(fld.orient)})", 3)
        w.extend(
            effects(
                fld.size,
                hjustify=fld.hjustify,
                vjustify=fld.vjustify,
                italic=fld.italic,
                bold=fld.bold,
                hidden=fld.hidden,
                indent=3,
            )
        )
        w.line(")", 2)

    w.line("(instances", 2)
    w.line(f'(project "{quote(ctx.project_name)}"', 3)
    w.line(f'(path "{ctx.sheet_path}"', 4)
    w.line(f'(reference "{quote(ref)}")', 5)
    w.line(f"(unit {unit})", 5)
    w.line(")", 4)
    w.line(")", 3)
    w.line(")", 2)
    w.line(")", 1)


def _emit_sheet(w: Writer, sheet: Sheet, ctx: SheetContext) -> None:
    uid = (
        timestamp_uuid(sheet.stamp)
        if sheet.stamp
        else stable_uuid(ctx.sheet_path, sheet.filename)
    )
    new_file = re.sub(r"\.sch$", ".kicad_sch", sheet.filename)

    w.line("(sheet", 1)
    w.line(f"(at {mm(sheet.x)} {mm(sheet.y)})", 2)
    w.line(f"(size {mm(sheet.w)} {mm(sheet.h)})", 2)
    w.line("(exclude_from_sim no)", 2)
    w.line("(in_bom yes)", 2)
    w.line("(on_board yes)", 2)
    w.line("(dnp no)", 2)
    w.line("(stroke", 2)
    w.line("(width 0.1524)", 3)
    w.line("(type solid)", 3)
    w.line(")", 2)
    w.line("(fill", 2)
    w.line("(color 0 0 0 0.0000)", 3)
    w.line(")", 2)
    w.line(f'(uuid "{uid}")', 2)

    w.line(f'(property "Sheetname" "{quote(sheet.name)}"', 2)
    w.line(f"(at {mm(sheet.x)} {mm(float(sheet.y) - 20)} 0)", 3)
    w.extend(effects("50", hjustify="L", vjustify="B", indent=3))
    w.line(")", 2)
    w.line(f'(property "Sheetfile" "{quote(new_file)}"', 2)
    w.line(f"(at {mm(sheet.x)} {mm(float(sheet.y) + float(sheet.h) + 20)} 0)", 3)
    w.extend(effects("50", hjustify="L", vjustify="T", indent=3))
    w.line(")", 2)

    for pin in sheet.pins:
        shape = SHAPE_TABLE.get(SHEET_PIN_FORM.get(pin.form, "UnSpc"), "passive")
        w.line(f'(pin "{quote(pin.name)}" {shape}', 2)
        w.line(f"(at {mm(pin.x)} {mm(pin.y)} {SHEET_PIN_ANGLE.get(pin.side, 0)})", 3)
        w.extend(effects(pin.size, indent=3))
        w.line(f'(uuid "{stable_uuid(uid, "pin", pin.index, pin.name)}")', 3)
        w.line(")", 2)

    w.line("(instances", 2)
    w.line(f'(project "{quote(ctx.project_name)}"', 3)
    w.line(f'(path "{ctx.sheet_path}"', 4)
    w.line('(page "2")', 5)
    w.line(")", 4)
    w.line(")", 3)
    w.line(")", 2)
    w.line(")", 1)
