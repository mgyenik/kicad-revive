"""Tests for netlist-vs-board verification."""

from __future__ import annotations

import pytest

from kicad_revive.verify import compare, parse_board, parse_netlist

NETLIST = """\
(export
\t(version "E")
\t(design)
\t(nets
\t\t(net
\t\t\t(code "1")
\t\t\t(name "VCC")
\t\t\t(node
\t\t\t\t(ref "R1")
\t\t\t\t(pin "1")
\t\t\t)
\t\t\t(node
\t\t\t\t(ref "C1")
\t\t\t\t(pin "1")
\t\t\t)
\t\t)
\t\t(net
\t\t\t(code "2")
\t\t\t(name "GND")
\t\t\t(node
\t\t\t\t(ref "R1")
\t\t\t\t(pin "2")
\t\t\t)
\t\t\t(node
\t\t\t\t(ref "C1")
\t\t\t\t(pin "2")
\t\t\t)
\t\t)
\t\t(net
\t\t\t(code "3")
\t\t\t(name "unconnected-(R9-Pad1)")
\t\t\t(node
\t\t\t\t(ref "R9")
\t\t\t\t(pin "1")
\t\t\t)
\t\t)
\t)
)
"""

LEGACY_BOARD = """\
(kicad_pcb (version 20171130)
  (module Resistor_SMD:R_0402 (layer F.Cu)
    (fp_text reference R1 (at 0 0))
    (pad 1 smd rect (at -0.5 0) (size 1 1) (layers F.Cu)
      (net 1 "VCC"))
    (pad 2 smd rect (at 0.5 0) (size 1 1) (layers F.Cu)
      (net 2 "GND"))
  )
  (module Capacitor_SMD:C_0402 (layer F.Cu)
    (fp_text reference C1 (at 0 0))
    (pad 1 smd rect (at -0.5 0) (size 1 1) (layers F.Cu)
      (net 1 "VCC"))
    (pad 2 smd rect (at 0.5 0) (size 1 1) (layers F.Cu)
      (net 2 "GND"))
  )
  (module Logo:OSHW (layer F.SilkS)
    (fp_text reference G*** (at 0 0))
  )
)
"""

MODERN_BOARD = """\
(kicad_pcb
\t(version 20241229)
\t(footprint "Resistor_SMD:R_0402"
\t\t(property "Reference" "R1")
\t\t(pad "1" smd rect
\t\t\t(at -0.5 0)
\t\t\t(net 1 "VCC")
\t\t)
\t\t(pad "2" smd rect
\t\t\t(at 0.5 0)
\t\t\t(net 2 "GND")
\t\t)
\t)
)
"""


@pytest.fixture
def netlist_file(tmp_path):
    path = tmp_path / "n.net"
    path.write_text(NETLIST, encoding="utf-8")
    return path


@pytest.fixture
def board_file(tmp_path):
    path = tmp_path / "b.kicad_pcb"
    path.write_text(LEGACY_BOARD, encoding="utf-8")
    return path


class TestParsing:
    def test_netlist_nodes(self, netlist_file):
        nets = parse_netlist(netlist_file)
        assert nets["VCC"] == {("R1", "1"), ("C1", "1")}
        assert nets["GND"] == {("R1", "2"), ("C1", "2")}

    def test_legacy_board_modules(self, board_file):
        nets, refs = parse_board(board_file)
        assert refs == {"R1", "C1", "G***"}
        assert nets["VCC"] == {("R1", "1"), ("C1", "1")}

    def test_modern_board_footprints(self, tmp_path):
        path = tmp_path / "m.kicad_pcb"
        path.write_text(MODERN_BOARD, encoding="utf-8")
        nets, refs = parse_board(path)
        assert refs == {"R1"}
        assert nets["VCC"] == {("R1", "1")}

    def test_netlist_without_nets_section(self, tmp_path):
        path = tmp_path / "empty.net"
        path.write_text("(export (version \"E\"))", encoding="utf-8")
        assert parse_netlist(path) == {}


class TestCompare:
    def test_matching_design_passes(self, netlist_file, board_file):
        result = compare(netlist_file, board_file)
        assert result.matched_nets == 2
        assert result.nets_ok
        assert not result.schematic_only
        assert not result.board_only

    def test_board_only_graphics_are_reported_but_do_not_fail(self, netlist_file, board_file):
        result = compare(netlist_file, board_file)
        # A logo footprint has no schematic symbol; that is normal, so it must
        # not be treated as a connectivity failure.
        assert result.missing_refs == {"G***"}
        assert result.nets_ok

    def test_single_node_nets_are_ignored(self, netlist_file, board_file):
        # "unconnected-(...)" pseudo-nets exist only in exports and would
        # otherwise appear as schematic-only nets on every project.
        result = compare(netlist_file, board_file)
        assert result.total_schematic_nets == 2

    def test_rewired_net_is_detected(self, tmp_path, netlist_file):
        broken = LEGACY_BOARD.replace('(net 2 "GND"))\n  )\n  (module Capacitor', '(net 1 "VCC"))\n  )\n  (module Capacitor')
        path = tmp_path / "broken.kicad_pcb"
        path.write_text(broken, encoding="utf-8")
        result = compare(netlist_file, path)
        assert not result.nets_ok

    def test_net_renamed_but_identically_wired_still_matches(self, tmp_path, netlist_file):
        # Nets are compared by node set, so a rename is not a rewire.
        renamed = LEGACY_BOARD.replace('"VCC"', '"+3V3"')
        path = tmp_path / "renamed.kicad_pcb"
        path.write_text(renamed, encoding="utf-8")
        result = compare(netlist_file, path)
        assert result.nets_ok
        assert result.matched_nets == 2

    def test_component_missing_from_board_is_flagged(self, tmp_path, netlist_file):
        reduced = "\n".join(
            line for line in LEGACY_BOARD.splitlines() if "Capacitor" not in line
        )
        path = tmp_path / "reduced.kicad_pcb"
        path.write_text(reduced, encoding="utf-8")
        result = compare(netlist_file, path)
        assert "C1" in result.extra_refs
        assert not result.ok
