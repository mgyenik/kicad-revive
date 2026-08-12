"""Building a modern ``lib_symbols`` block from a legacy cache library.

Legacy schematics reference symbols by ``Library:Name`` and store no geometry;
modern ones embed a full definition of every symbol used.  The project's
``<project>-cache.lib`` is the right source for that geometry: KiCad wrote it
alongside the schematic and it contains exactly the symbols in use, at the
revision they were used.  Pulling from the current stock libraries instead
would silently substitute whatever those symbols look like today.

``.lib`` is itself a legacy format, but -- unlike the schematic importer -- the
*symbol library* importer still works in every KiCad release, so
``kicad-cli sym upgrade`` converts the cache for us and we lift definitions out
of the result.
"""

from __future__ import annotations

import re
from pathlib import Path

from .sexpr import find_blocks_with_indent, quote, reindent


def available_symbols(kicad_sym_text: str) -> dict[str, str]:
    """Map symbol name -> raw block, for each top-level symbol in a library."""
    found: dict[str, str] = {}
    for block in find_blocks_with_indent(kicad_sym_text, '(symbol "', depth=1):
        match = re.search(r'\(symbol\s+"((?:[^"\\]|\\.)*)"', block)
        if match:
            found[match.group(1)] = block
    return found


def build_lib_symbols(
    cache_path: Path,
    lib_ids: set[str],
    warnings: list[str],
    *,
    indent: int = 2,
) -> list[str]:
    """Extract *lib_ids* from a converted cache library, ready to embed.

    A cache library flattens ``Device:C`` to a single symbol named ``Device_C``
    whose sub-units are ``Device_C_0_1``.  A ``lib_symbols`` block wants
    ``Device:C`` with sub-units ``C_0_1``.  The split point between library and
    symbol name is ambiguous on its own (``Connector_Generic_Conn_01x02`` could
    divide several ways), so it is resolved from the ``lib_id`` the schematic
    actually referenced rather than guessed.
    """
    text = Path(cache_path).read_text(encoding="utf-8", errors="replace")
    available = available_symbols(text)
    blocks: list[str] = []

    for lib_id in sorted(lib_ids):
        if ":" not in lib_id:
            warnings.append(f"symbol {lib_id!r} has no library prefix; skipped")
            continue
        library, name = lib_id.split(":", 1)
        flat = f"{library}_{name}"

        key = flat if flat in available else (name if name in available else None)
        if key is None:
            warnings.append(
                f"symbol {lib_id!r} not found in cache library "
                f"(looked for {flat!r}); it will be missing from lib_symbols"
            )
            continue

        block = available[key]
        block = block.replace(f'(symbol "{key}"', f'(symbol "{quote(lib_id)}"', 1)
        block = re.sub(
            r'\(symbol\s+"' + re.escape(key) + r"_",
            '(symbol "' + quote(name) + "_",
            block,
        )
        blocks.append(reindent(block, indent))

    return blocks
