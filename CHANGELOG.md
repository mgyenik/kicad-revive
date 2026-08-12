# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- A stale `.kicad_sym` beside the cache library was treated as a successful
  conversion, so symbols from a different KiCad version could be embedded in
  the schematic. The target KiCad then refused the file with only "Failed to
  load schematic" to go on. The destination is now removed first and success
  is judged on kicad-cli's exit status.
- The emitted schematic format version is now derived from the `kicad-cli` in
  use instead of being hard-coded, so symbols and schematic always target the
  same KiCad release.
- Failing to convert a legacy `.lib` now explains that KiCad 7 and earlier
  cannot read them, rather than surfacing a bare kicad-cli message.

## [0.1.0] - 2026-08-12

Initial release.

### Added
- `rescue` — convert a whole legacy project: cache library, all schematics in
  the hierarchy, project-local symbol libraries, `sym-lib-table`, `.kicad_pro`;
  then verify against the board and archive the legacy sources.
- `convert` — convert a single legacy `.sch` and its sub-sheets.
- `verify` — compare any schematic's netlist against a `.kicad_pcb`, matching
  nets by node set rather than by name. Works on projects this tool never
  touched.
- Legacy `.sch` support for components (including multi-unit symbols and
  hierarchical `AR` instance references), wires, notes lines, buses, bus
  entries, junctions, no-connects, labels, global and hierarchical labels, text
  notes, hierarchical sheets and their pins, embedded bitmaps, page setup and
  title block.
- Deterministic output: converting the same input twice is byte-identical.
