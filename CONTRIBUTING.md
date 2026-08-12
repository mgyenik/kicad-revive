# Contributing

## Setup

```console
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest && ruff check . && mypy
```

Tests that shell out to a real KiCad are marked `kicad_cli` and skip when it is
absent. Run `pytest -m "not kicad_cli"` to match what CI's unit job does.

## The one rule that matters

**Every conversion rule must be justified by evidence, and the evidence must be
written down.**

This tool converts a file format whose behaviour is not fully documented, and
whose failure modes are silent. Output that loads, renders, and looks entirely
plausible can still be wrong: a mirrored symbol, a field on the wrong side, a
label anchored at the wrong end. None of that raises an error, and none of it
is obvious from reading the output.

So when you change or add a conversion rule:

1. Establish it from something real — a rendered diff against a PDF exported by
   the KiCad version that wrote the file, or the file's own geometry (for
   instance: which way does the wire leave this label's anchor?).
2. Record *what* established it, in the docstring and in the test. A future
   reader must be able to tell a deliberate rule from a guess that happened to
   work on one project.
3. Add a test that would fail if the rule were reverted.

`src/kicad_revive/geometry.py` and `tests/test_geometry.py` are the model.

## Verifying against a real project

The strongest check available is a netlist comparison against a PCB laid out
from the original schematic. The board's net assignments were written by the
old KiCad from the old schematic, so they are evidence that predates — and is
independent of — the conversion:

```console
kicad-revive verify myproject.kicad_sch myproject.kicad_pcb
```

Anything short of every node set matching is a bug worth chasing.

Rendering both versions and diffing the images is how all three of the
non-obvious rules in `geometry.py` were found. It is slow but it works, and it
catches things a netlist cannot: text placement, justification, rotation.

## Adding support for a construct

Unhandled records append to `Schematic.warnings` rather than being dropped, so
running the tool over a project that uses something new will tell you what is
missing. Please add a fixture to `tests/data/` that exercises it.

## Style

Ruff and mypy are enforced in CI. Comments should explain *why*, particularly
where the code looks wrong but is right — the legacy identity matrix being
`(1,0,0,-1)` is the canonical example.
