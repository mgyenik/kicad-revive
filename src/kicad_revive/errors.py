"""Exception types raised by kicad-revive."""

from __future__ import annotations


class KicadReviveError(Exception):
    """Base class for every error this package raises deliberately."""


class NotLegacyFormat(KicadReviveError):
    """The input is not a legacy KiCad file."""


class MissingSymbols(KicadReviveError):
    """Symbols referenced by a schematic were not found in the cache library."""


class KicadCliNotFound(KicadReviveError):
    """kicad-cli could not be located."""


class SymbolLibraryConversionFailed(KicadReviveError):
    """kicad-cli could not convert a legacy symbol library."""


class VerificationFailed(KicadReviveError):
    """A converted schematic did not match the board it was checked against."""


class OutputExists(KicadReviveError):
    """Refusing to overwrite an existing file."""
