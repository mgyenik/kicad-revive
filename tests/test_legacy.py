"""Tests for the legacy .sch and .pro readers."""

from __future__ import annotations

import pytest

from kicad_revive.errors import NotLegacyFormat
from kicad_revive.legacy import parse_project, parse_schematic, tokenize, unescape


class TestTokenize:
    def test_splits_on_runs_of_whitespace(self):
        assert tokenize("F 0 x  y") == ["F", "0", "x", "y"]

    def test_keeps_quoted_strings_whole(self):
        assert tokenize('F 1 "hello world" H') == ["F", "1", "hello world", "H"]

    def test_handles_empty_quoted_string(self):
        assert tokenize('Comment1 ""') == ["Comment1", ""]

    def test_handles_escaped_quote_inside_string(self):
        assert tokenize(r'F 1 "a\"b"') == ["F", "1", r"a\"b"]


class TestUnescape:
    def test_newline_escape(self):
        assert unescape(r"1.1v @ 1A\n") == "1.1v @ 1A\n"

    def test_literal_backslash(self):
        assert unescape(r"a\\b") == "a\\b"

    def test_leaves_other_escapes_alone(self):
        assert unescape(r"C:\temp") == "C:\\temp"


class TestParseSchematic:
    def test_rejects_a_non_legacy_file(self, tmp_path):
        path = tmp_path / "modern.kicad_sch"
        path.write_text("(kicad_sch (version 20250114))", encoding="utf-8")
        with pytest.raises(NotLegacyFormat):
            parse_schematic(path)

    def test_rejects_the_stub_kicad_writes_over_a_legacy_file(self, tmp_path):
        # This is the exact damage KiCad 10 does: a 10-byte file containing
        # only the magic word. It must be refused, not silently converted to an
        # empty schematic.
        path = tmp_path / "stub.sch"
        path.write_text("EESchema\r\n", encoding="utf-8")
        with pytest.raises(NotLegacyFormat):
            parse_schematic(path)

    def test_title_block(self, tiny_root):
        sch = parse_schematic(tiny_root)
        assert sch.title == "tiny test board"
        assert sch.rev == "0.1"
        assert sch.company == "kicad-revive"
        assert sch.paper == "A4"

    def test_counts(self, tiny_root):
        sch = parse_schematic(tiny_root)
        assert len(sch.components) == 3
        assert len(sch.wires) == 4  # three wires plus one notes line
        assert len(sch.junctions) == 1
        assert len(sch.noconns) == 1
        assert len(sch.texts) == 4
        assert len(sch.sheets) == 1

    def test_parses_without_warnings(self, tiny_root):
        assert parse_schematic(tiny_root).warnings == []

    def test_orientation_matrices(self, tiny_root):
        by_ref = {c.ref: c for c in parse_schematic(tiny_root).components}
        assert by_ref["R1"].matrix == (1, 0, 0, -1)
        assert by_ref["C1"].matrix == (0, -1, -1, 0)
        assert by_ref["#PWR0101"].matrix == (1, 0, 0, 1)

    def test_lib_ids(self, tiny_root):
        assert parse_schematic(tiny_root).lib_ids == {"Device:R", "Device:C", "power:GND"}

    def test_fields(self, tiny_root):
        r1 = next(c for c in parse_schematic(tiny_root).components if c.ref == "R1")
        by_number = {f.number: f for f in r1.fields}
        assert by_number[0].text == "R1"
        assert by_number[1].text == "10k"
        assert by_number[2].hidden, "footprint field is flagged invisible"
        assert not by_number[0].hidden

    def test_field_orientation_letter_is_preserved(self, tiny_root):
        c1 = next(c for c in parse_schematic(tiny_root).components if c.ref == "C1")
        assert next(f for f in c1.fields if f.number == 0).orient == "V"

    def test_sheet(self, tiny_root):
        sheet = parse_schematic(tiny_root).sheets[0]
        assert sheet.filename == "sub.sch"
        assert sheet.name == "sub"
        assert sheet.stamp == "5E0C0100"
        assert len(sheet.pins) == 1
        assert sheet.pins[0].name == "ENABLE"
        assert sheet.pins[0].form == "I"

    def test_text_kinds_and_shapes(self, tiny_root):
        texts = parse_schematic(tiny_root).texts
        kinds = sorted(t.kind for t in texts)
        assert kinds == ["GLabel", "GLabel", "Label", "Notes"]
        glabels = {t.text: t for t in texts if t.kind == "GLabel"}
        assert glabels["VIN"].shape == "Input"
        assert glabels["VSENSE"].shape == "Output"
        assert glabels["VSENSE"].orient == 2

    def test_wire_kinds(self, tiny_root):
        kinds = [w.kind for w in parse_schematic(tiny_root).wires]
        assert kinds.count("Wire Line") == 3
        assert kinds.count("Notes Line") == 1

    def test_hierarchical_instance_references(self, tiny_sub):
        comp = parse_schematic(tiny_sub).components[0]
        assert len(comp.instances) == 2
        assert comp.instances[1]["Path"] == "/5E0C0100/5E0C0201"
        assert comp.instances[1]["Ref"] == "R2"


class TestParseProject:
    def test_reads_sections(self, tmp_path):
        path = tmp_path / "p.pro"
        path.write_text(
            "[pcbnew]\nCopperLayerCount=4\nMinHoleToHole=0.25\n"
            "[schematic_editor]\nLabSize=197\n",
            encoding="utf-8",
        )
        project = parse_project(path)
        assert project.get("pcbnew", "CopperLayerCount") == "4"
        assert project.get("schematic_editor", "LabSize") == "197"

    def test_identifies_settings_the_board_file_does_not_carry(self, tmp_path):
        # Netclasses and track minimums live in the .kicad_pcb and are read
        # from there; only a few DRC toggles are unique to the .pro.
        path = tmp_path / "p.pro"
        path.write_text(
            "[pcbnew]\nCopperLayerCount=4\nMinTrackWidth=0.15\nMinHoleToHole=0.25\n",
            encoding="utf-8",
        )
        orphans = parse_project(path).board_only_settings
        assert "MinHoleToHole" in orphans
        assert "MinTrackWidth" not in orphans
        assert "CopperLayerCount" not in orphans
