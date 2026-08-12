"""Tests for the .kicad_sch writer."""

from __future__ import annotations

import re

import pytest

from kicad_revive.emit import SheetContext, emit_schematic, stable_uuid, timestamp_uuid
from kicad_revive.legacy import parse_schematic
from kicad_revive.symbols import build_lib_symbols


@pytest.fixture
def rendered(tiny_root, tiny_cache):
    sch = parse_schematic(tiny_root)
    warnings: list[str] = []
    blocks = build_lib_symbols(tiny_cache, sch.lib_ids, warnings)
    assert warnings == [], warnings
    context = SheetContext(
        project_name="tiny",
        root_uuid=stable_uuid("root", "tiny"),
        sheet_path="/" + stable_uuid("root", "tiny"),
        sheet_uuid=stable_uuid("root", "tiny"),
    )
    return emit_schematic(sch, context, lib_blocks=blocks)


class TestUuids:
    def test_legacy_timestamp_uses_kicads_own_convention(self):
        # Confirmed against KiCad's own netlist export: sheet stamp 5F109712
        # appears as 00000000-0000-0000-0000-00005f109712. Matching it keeps
        # hierarchical instance paths comparable with KiCad-produced files.
        assert timestamp_uuid("5F109712") == "00000000-0000-0000-0000-00005f109712"

    def test_timestamp_is_lowercased_and_padded(self):
        assert timestamp_uuid("ABC") == "00000000-0000-0000-0000-000000000abc"

    def test_stable_uuid_is_deterministic(self):
        assert stable_uuid("a", "b") == stable_uuid("a", "b")
        assert stable_uuid("a", "b") != stable_uuid("a", "c")


class TestDocumentStructure:
    def test_starts_with_kicad_sch_form(self, rendered):
        assert rendered.startswith("(kicad_sch\n")

    def test_parentheses_balance(self, rendered):
        depth = 0
        in_string = False
        escaped = False
        for ch in rendered:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string:
                depth += (ch == "(") - (ch == ")")
            assert depth >= 0
        assert depth == 0

    def test_no_literal_newline_inside_a_quoted_atom(self, rendered):
        # The failure mode this guards is total: KiCad refuses the whole file
        # and names only the file in the error.
        in_string = False
        escaped = False
        for ch in rendered:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = not in_string
            elif ch == "\n":
                assert not in_string, "literal newline inside a quoted string"

    def test_title_block_carried_over(self, rendered):
        assert '(title "tiny test board")' in rendered
        assert '(rev "0.1")' in rendered
        assert '(company "kicad-revive")' in rendered

    def test_paper_emitted_by_name(self, rendered):
        assert '(paper "A4")' in rendered


class TestContent:
    def test_every_symbol_present(self, rendered):
        assert len(re.findall(r"^\t\(symbol$", rendered, re.M)) == 3

    def test_lib_symbols_are_embedded_and_renamed(self, rendered):
        assert '(symbol "Device:R"' in rendered
        assert '(symbol "Device:C"' in rendered
        assert '(symbol "power:GND"' in rendered
        # sub-units are renamed from the cache's flattened form
        assert '(symbol "R_0_1"' in rendered
        assert "Device_R_0_1" not in rendered

    def test_wires_and_notes_line_use_different_forms(self, rendered):
        assert len(re.findall(r"^\t\(wire$", rendered, re.M)) == 3
        assert len(re.findall(r"^\t\(polyline$", rendered, re.M)) == 1

    def test_junction_and_no_connect(self, rendered):
        assert "(junction" in rendered
        assert "(no_connect" in rendered

    def test_label_kinds(self, rendered):
        assert '(label "VOUT"' in rendered
        assert '(global_label "VIN"' in rendered
        assert '(global_label "VSENSE"' in rendered
        assert '(text "Power Supply Section"' in rendered

    def test_global_label_shapes_preserved(self, rendered):
        vin = rendered[rendered.index('(global_label "VIN"') :][:200]
        assert "(shape input)" in vin
        vsense = rendered[rendered.index('(global_label "VSENSE"') :][:200]
        assert "(shape output)" in vsense

    def test_rotated_symbol_gets_an_angle(self, rendered):
        block = rendered[rendered.index('(lib_id "Device:C")') :][:200]
        assert "(at 101.6 50.8 90)" in block

    def test_mirrored_symbol_gets_a_mirror(self, rendered):
        block = rendered[rendered.index('(lib_id "power:GND")') :][:200]
        assert "(mirror x)" in block

    def test_sheet_reference_is_rewritten_to_modern_extension(self, rendered):
        assert '(property "Sheetfile" "sub.kicad_sch"' in rendered
        assert "sub.sch" not in rendered

    def test_sheet_pin_converted(self, rendered):
        assert '(pin "ENABLE" input' in rendered

    def test_hidden_fields_marked_hidden(self, rendered):
        footprint = rendered[rendered.index('(property "Footprint"') :][:400]
        assert "(hide yes)" in footprint


class TestDeterminism:
    def test_same_input_produces_identical_output(self, tiny_root, tiny_cache):
        def render():
            sch = parse_schematic(tiny_root)
            blocks = build_lib_symbols(tiny_cache, sch.lib_ids, [])
            ctx = SheetContext("tiny", stable_uuid("root", "tiny"), "/x", "u")
            return emit_schematic(sch, ctx, lib_blocks=blocks)

        assert render() == render()


class TestHierarchicalInstances:
    def test_sub_sheet_reference_resolves_via_ar_record(self, tiny_sub, tiny_cache):
        sch = parse_schematic(tiny_sub)
        root_uuid = stable_uuid("root", "tiny")
        sheet_uuid = timestamp_uuid("5E0C0100")
        context = SheetContext(
            project_name="tiny",
            root_uuid=root_uuid,
            sheet_path=f"/{root_uuid}/{sheet_uuid}",
            sheet_uuid=stable_uuid("sheetfile", "sub.sch"),
        )
        rendered = emit_schematic(
            sch, context, lib_blocks=build_lib_symbols(tiny_cache, sch.lib_ids, [])
        )
        # The legacy AR path's final element is the symbol's own stamp, so the
        # sheet path is everything before it -- resolving "R?" to "R2" here.
        assert '(reference "R2")' in rendered
        assert '(property "Reference" "R2"' in rendered
        assert "R?" not in rendered
