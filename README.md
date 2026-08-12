# kicad-revive

Bring a legacy KiCad project forward to the modern file format — and **verify
the result against the board it was laid out from**.

```console
$ kicad-revive rescue ./myboard

  myboard  ~/projects/myboard

  symbols       myboard-cache.kicad_sym  (27 used)
  library       Lattice_ECP_FPGA.kicad_sym
  library       clock.kicad_sym
  schematics    myboard.kicad_sch, fpga.kicad_sch  (202 symbols)
  libraries     wrote sym-lib-table
  project       wrote myboard.kicad_pro
  board         myboard.kicad_pcb  v20171130 — readable, left as-is
  archived      legacy sources -> legacy/

  verify  schematic netlist vs. board
    nets          107/107 node sets identical
    components    73/74 matched
    board-only    G***  (board graphics have no symbol — usually fine)

  rescued — open myboard.kicad_pro in KiCad
```

## Why this exists

KiCad 8 and later cannot import legacy EESchema schematics (`.sch`). That would
be fine, except **the failure is silent and destructive**. Observed on KiCad
10.0.3:

| Operation | Result |
|---|---|
| `kicad-cli sch export pdf legacy.sch` | renders the sheet correctly — *looks like it works* |
| `kicad-cli sch export netlist legacy.sch` | **0 components, 0 nets** |
| `kicad-cli sch upgrade legacy.sch` | `Expecting '(' … line 1, offset 1` |
| GUI **File → Save As** | **overwrites the `.sch` with a 10-byte stub** containing only `EESchema` |

The plot succeeding is what makes it dangerous. The schematic looks right on
screen, so you save — and the original is gone.

Upstream reports: [#22415](https://gitlab.com/kicad/code/kicad/-/issues/22415)
(KiCad looks for a `.kicad_sch` that doesn't exist and silently creates a blank
root sheet) and [#17202](https://gitlab.com/kicad/code/kicad/-/issues/17202)
(KiCad 8 corrupts custom field names on legacy import).

KiCad 7 is the last release whose *GUI* can import these files. Its `kicad-cli`
cannot — it accepts only `.kicad_sch`. So there is no supported command-line
path at all.

**If you still have an intact legacy project: back it up before opening it in
KiCad 8+.**

## What it does

`kicad-revive rescue` takes a whole project directory and:

1. converts `<project>-cache.lib` and any project-local `.lib` symbol libraries
   to `.kicad_sym` (via `kicad-cli`, whose *symbol library* importer still works)
2. converts every schematic in the hierarchy to `.kicad_sch`, embedding symbol
   geometry from the cache — the symbols as they were used, not as they look in
   today's stock libraries
3. writes a `sym-lib-table` so project-local libraries actually resolve
4. writes a `.kicad_pro`
5. leaves the `.kicad_pcb` alone — pcbnew's format has been backward-compatible
   since KiCad 4, so a 2017-era board opens in KiCad 10 untouched
6. **verifies** the conversion against the board
7. moves the legacy sources into `legacy/` so KiCad cannot reopen and stub them

## Install

```console
pip install kicad-revive
```

Requires Python 3.10+ and a KiCad installation (for `kicad-cli`). It is found on
`PATH`, via `$KICAD_CLI`, in the usual install locations, or with `--kicad-cli`.

**KiCad 8 or newer is needed.** Symbol geometry comes from the project's legacy
`.lib` cache, and `kicad-cli` from KiCad 7 and earlier rejects `.lib` files
outright. Tested against KiCad 9 and 10.

The emitted `.kicad_sch` format version matches whichever `kicad-cli` is used,
so the embedded symbols and the schematic containing them always target the
same KiCad. Override with `--format-version` if you need something else.

## Usage

```console
kicad-revive rescue ./myproject                     # convert and verify in place
kicad-revive rescue ./myproject --out-dir ./modern  # convert into a copy
kicad-revive convert myproject.sch                  # one schematic and its sub-sheets
kicad-revive verify myproject.kicad_sch myproject.kicad_pcb
```

`verify` works on any KiCad project, not only converted ones. Exit code is `2`
if verification fails, so it drops into CI.

## Verification, and why it matters

A converted schematic that opens and renders correctly can still be wrong, and
reading it will not tell you — a mirrored symbol or a mis-anchored label looks
entirely plausible.

If the project has a PCB, there is an independent record of what the
connectivity was *supposed* to be: the board's own net assignments, written by
whichever old KiCad laid it out, from the schematic as it was then. Comparing
against it checks the conversion using evidence that predates the conversion.

Nets are matched by **node set** — the set of (reference, pad) pairs they
connect — not by name, so a renamed net is not mistaken for a rewired one.

On the project this tool was built for (`basic-ecp5-pcb`, KiCad 5.1.6, 202
symbols across two sheets), the result was **107 of 107 multi-node nets
matching exactly, with zero discrepancies**, and every component present. The
only board item without a schematic symbol was the OSHW logo — a graphic, as
expected.

## Three things that are easy to get wrong

Each was found by rendering the output and diffing it against a PDF that KiCad
5.1 itself exported in 2020. All three fail silently.

**1. Field positions are in library coordinates, not sheet coordinates.**
A legacy field position is the symbol origin plus an offset in *library* space
(Y up); the orientation matrix maps that to sheet space (Y down). This is why
the legacy identity matrix is `(1,0,0,-1)` and not `(1,0,0,1)`. Copy field
positions through unchanged and you misplace every field on every rotated
symbol — *and* silently swap each symbol's reference and value vertically, even
on unrotated ones.

**2. Position is absolute, but angle is relative.** KiCad stores a property's
position absolutely, yet adds the symbol's rotation to its angle when
rendering. So positions must be transformed and angles must not.

**3. Global labels anchor at the opposite end from plain labels.** A plain
label at orientation 0 extends right from its anchor; a *global* label at
orientation 0 extends **left**, because the anchor is the connecting end. The
modern equivalent is rotated 180°.

And one that costs an afternoon: legacy `\n` inside text must stay **escaped**
in the output. A literal newline in a quoted atom makes KiCad reject the entire
file, and the parse error names only the file — not the line, not the element.

`kicad-cli sch upgrade` is a useful linter while developing: on a modern file it
reports a real parse error, where `sch export` only says "Failed to load
schematic".

## Supported constructs

Components (including multi-unit symbols and hierarchical `AR` instance
references), wires, notes lines, buses, bus entries, junctions, no-connects,
labels, global and hierarchical labels, text notes, hierarchical sheets and
their pins, embedded bitmaps, page setup and title block.

Anything unrecognised is reported as a warning, never dropped silently.

Output is deterministic — UUIDs are derived from legacy timestamps using
KiCad's own convention (`00000000-0000-0000-0000-` + the timestamp), or from
content where the legacy format had no stamp. Converting the same input twice
is byte-identical, so conversions are reviewable in version control.

## Limitations

- Buses, bus entries and hierarchical sheet pins are implemented from the
  format spec but were not present in the project this was validated against.
  Check the verification output before trusting them.
- Symbol geometry comes from the project's cache library. Without one, symbols
  cannot be embedded and the tool says so.
- ERC will report `lib_symbol_mismatch` warnings after conversion. That is
  expected: the embedded symbols are the historical ones and differ cosmetically
  from today's stock libraries. Use **Tools → Update Symbols from Library** if
  you want them refreshed.

## Format references

- Legacy: [legacy_file_format_documentation.pdf](https://dev-docs.kicad.org/en/file-formats/legacy-4-to-6/legacy_file_format_documentation.pdf)
- Modern: [s-expression schematic format](https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/index.html)

## Development

```console
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && mypy
```

Tests needing a real KiCad are marked `kicad_cli` and skip when it is absent:

```console
pytest -m "not kicad_cli"
```

## License

MIT. The converter is clean-room: written from the published format
specifications and from observed behaviour, not from KiCad's source.

The test fixture project is derived from Matt Venn's
[basic-ecp5-pcb](https://github.com/mattvenn/basic-ecp5-pcb), released under
CC0.
