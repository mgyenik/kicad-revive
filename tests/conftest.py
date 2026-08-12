"""Shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"
TINY = DATA / "tiny"


@pytest.fixture
def tiny_root() -> Path:
    return TINY / "tiny.sch"


@pytest.fixture
def tiny_sub() -> Path:
    return TINY / "sub.sch"


@pytest.fixture
def tiny_cache() -> Path:
    return TINY / "tiny-cache.kicad_sym"


@pytest.fixture
def tiny_project(tmp_path) -> Path:
    """A writable copy of the tiny legacy project."""
    destination = tmp_path / "tiny"
    shutil.copytree(TINY, destination)
    return destination


@pytest.fixture(scope="session")
def kicad_cli_path(tmp_path_factory):
    """A kicad-cli that can actually convert legacy symbol libraries.

    Capability is probed rather than inferred from a version number: KiCad 7's
    CLI rejects legacy .lib files outright, so the whole rescue path is
    unavailable there, but which releases can do it is not something to hard-code.
    """
    from kicad_revive.errors import KicadCliNotFound, SymbolLibraryConversionFailed
    from kicad_revive.kicad_cli import find_kicad_cli, upgrade_symbol_library

    try:
        cli = find_kicad_cli()
    except KicadCliNotFound:
        pytest.skip("kicad-cli not available")

    probe = tmp_path_factory.mktemp("probe")
    try:
        upgrade_symbol_library(cli, TINY / "tiny-cache.lib", probe / "probe.kicad_sym")
    except SymbolLibraryConversionFailed as exc:
        pytest.skip(f"this kicad-cli cannot convert legacy .lib libraries: {exc}")
    return cli
