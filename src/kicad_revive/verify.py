"""Verifying a converted schematic against the board laid out from it.

This is the part worth having.  A converted schematic that opens and renders
correctly can still be wrong, and reading it will not tell you -- a mirrored
symbol or a mis-anchored label looks entirely plausible.

If the project has a PCB, though, there is an independent record of what the
connectivity was *supposed* to be: the board's own net assignments, written by
whichever old KiCad laid it out, from the schematic as it was then.  Comparing
the converted schematic's netlist against it checks the conversion against
evidence that predates the conversion.

Nets are compared by their **node sets** -- the set of (reference, pad) pairs
they connect -- not by name, so a renamed net is not mistaken for a rewired one.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .sexpr import find_blocks, find_blocks_matching


@dataclass
class Comparison:
    """Result of checking a schematic netlist against a board."""

    matched_nets: int = 0
    schematic_only: list[tuple[str, frozenset]] = field(default_factory=list)
    board_only: list[tuple[str, frozenset]] = field(default_factory=list)
    schematic_refs: set[str] = field(default_factory=set)
    board_refs: set[str] = field(default_factory=set)
    total_schematic_nets: int = 0
    total_board_nets: int = 0

    @property
    def missing_refs(self) -> set[str]:
        """On the board but absent from the schematic.

        Usually legitimate: logos, fiducials and mounting art are placed
        directly on the board and have no symbol.
        """
        return self.board_refs - self.schematic_refs

    @property
    def extra_refs(self) -> set[str]:
        return self.schematic_refs - self.board_refs

    @property
    def nets_ok(self) -> bool:
        return not self.schematic_only and not self.board_only

    @property
    def ok(self) -> bool:
        return self.nets_ok and not self.extra_refs


#: Matches the head of a ``(net ...)`` form in either netlist layout.
#:
#: KiCad's netlist writer changed presentation between releases: KiCad 9 and
#: earlier emit compact forms (``(comp (ref "R1")`` on one line) while KiCad 10
#: pretty-prints one token per line. Matching only the pretty-printed shape
#: made verification silently report zero nets on KiCad 9 -- a false failure,
#: which is worse than no check at all because it discredits a correct
#: conversion.
_NET_HEAD = re.compile(r"\(net\s")

#: ``(ref ...)`` and ``(pin ...)`` may be separated by a newline or a space.
_NODE = re.compile(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)')


def parse_netlist(path: Path) -> dict[str, set[tuple[str, str]]]:
    """Read a KiCad netlist export into ``{net_name: {(ref, pin), ...}}``.

    Tolerates both the compact and pretty-printed netlist layouts.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    index = text.find("(nets")
    if index < 0:
        return {}

    nets: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for block in find_blocks_matching(text[index:], _NET_HEAD):
        name = re.search(r'\(name "([^"]*)"\)', block)
        if not name:
            continue
        for node in _NODE.finditer(block):
            nets[name.group(1)].add((node.group(1), node.group(2)))
    return dict(nets)


def parse_board(path: Path) -> tuple[dict[str, set[tuple[str, str]]], set[str]]:
    """Read a ``.kicad_pcb`` into ``({net_name: {(ref, pad)}}, {refs})``.

    Handles both the legacy ``(module ...)`` keyword and the modern
    ``(footprint ...)`` one, so it works on boards from KiCad 4 onwards.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    nets: dict[str, set[tuple[str, str]]] = defaultdict(set)
    refs: set[str] = set()

    for keyword in ("(module ", "(footprint "):
        for block in find_blocks(text, keyword):
            ref_match = re.search(r"\(fp_text reference (\S+)", block) or re.search(
                r'\(property "Reference" "([^"]*)"', block
            )
            if not ref_match:
                continue
            ref = ref_match.group(1).strip('"')
            refs.add(ref)
            for pad in find_blocks(block, "(pad "):
                pad_match = re.match(r'\(pad ("[^"]*"|\S+)', pad)
                net_match = re.search(r'\(net \d+ ("[^"]*"|\S+?)\)', pad)
                if pad_match and net_match:
                    nets[net_match.group(1).strip('"')].add(
                        (ref, pad_match.group(1).strip('"'))
                    )
    return dict(nets), refs


def compare(netlist_path: Path, board_path: Path) -> Comparison:
    """Compare a schematic netlist against a board's net assignments."""
    schematic_nets = parse_netlist(netlist_path)
    board_nets, board_refs = parse_board(board_path)

    schematic_refs = {ref for nodes in schematic_nets.values() for ref, _ in nodes}

    def significant(nets: dict[str, set[tuple[str, str]]]) -> dict[str, frozenset]:
        # Single-node nets carry no connectivity information, and KiCad names
        # them "unconnected-(...)" in exports but simply omits them from the
        # board -- so including them would produce noise, not signal.
        return {
            name: frozenset(nodes)
            for name, nodes in nets.items()
            if len(nodes) > 1 and name and not name.startswith("unconnected-")
        }

    sch_sig = significant(schematic_nets)
    brd_sig = significant(board_nets)
    sch_sets = set(sch_sig.values())
    brd_sets = set(brd_sig.values())

    return Comparison(
        matched_nets=len(sch_sets & brd_sets),
        schematic_only=[(n, s) for n, s in sch_sig.items() if s not in brd_sets],
        board_only=[(n, s) for n, s in brd_sig.items() if s not in sch_sets],
        schematic_refs=schematic_refs,
        board_refs=board_refs,
        total_schematic_nets=len(sch_sig),
        total_board_nets=len(brd_sig),
    )
