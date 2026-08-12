"""Bring legacy KiCad projects forward to the modern file format.

KiCad 8 and later cannot import legacy EESchema schematics, and the failure is
silent: the sheet plots correctly but loads zero symbols, so saving overwrites
the original with an empty stub. This package converts such projects offline
and verifies the result against the board they were laid out from.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .errors import (
    KicadCliNotFound,
    KicadReviveError,
    MissingSymbols,
    NotLegacyFormat,
    OutputExists,
    SymbolLibraryConversionFailed,
    VerificationFailed,
)
from .legacy import Schematic, parse_project, parse_schematic
from .rescue import RescueResult, rescue_project
from .verify import Comparison, compare

__all__ = [
    "Comparison",
    "KicadCliNotFound",
    "KicadReviveError",
    "MissingSymbols",
    "NotLegacyFormat",
    "OutputExists",
    "RescueResult",
    "Schematic",
    "SymbolLibraryConversionFailed",
    "VerificationFailed",
    "__version__",
    "compare",
    "parse_project",
    "parse_schematic",
    "rescue_project",
]
