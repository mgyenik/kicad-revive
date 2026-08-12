"""Tests for project discovery and the end-to-end rescue.

Tests that shell out to a real KiCad are marked ``kicad_cli`` and skip when it
is not installed, so the suite stays runnable in CI without KiCad.
"""

from __future__ import annotations

import pytest

from kicad_revive.errors import NotLegacyFormat
from kicad_revive.rescue import collect_sheets, find_root_schematic, rescue_project


class TestRootDiscovery:
    def test_picks_the_sheet_nobody_references(self, tiny_project):
        assert find_root_schematic(tiny_project).name == "tiny.sch"

    def test_returns_none_when_no_legacy_schematics(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
        assert find_root_schematic(tmp_path) is None

    def test_ignores_a_modern_schematic(self, tmp_path):
        (tmp_path / "x.sch").write_text("(kicad_sch)", encoding="utf-8")
        assert find_root_schematic(tmp_path) is None

    def test_ignores_a_kicad_stubbed_file(self, tmp_path):
        # The 10-byte stub KiCad leaves behind is not a usable root.
        (tmp_path / "dead.sch").write_text("EESchema\r\n", encoding="utf-8")
        (tmp_path / "good.sch").write_text(
            "EESchema Schematic File Version 4\n$EndSCHEMATC\n", encoding="utf-8"
        )
        assert find_root_schematic(tmp_path).name == "good.sch"


class TestCollectSheets:
    def test_walks_the_hierarchy(self, tiny_project):
        sheets, warnings = collect_sheets(tiny_project / "tiny.sch", "tiny")
        assert [s.source.name for s in sheets] == ["tiny.sch", "sub.sch"]
        assert warnings == []

    def test_child_path_nests_under_the_root(self, tiny_project):
        sheets, _ = collect_sheets(tiny_project / "tiny.sch", "tiny")
        root, child = sheets
        assert child.context.sheet_path.startswith(root.context.sheet_path + "/")

    def test_child_sheet_uuid_comes_from_the_legacy_stamp(self, tiny_project):
        sheets, _ = collect_sheets(tiny_project / "tiny.sch", "tiny")
        assert sheets[1].context.sheet_path.endswith("00000000-0000-0000-0000-00005e0c0100")

    def test_missing_child_sheet_warns_instead_of_raising(self, tiny_project):
        (tiny_project / "sub.sch").unlink()
        sheets, warnings = collect_sheets(tiny_project / "tiny.sch", "tiny")
        assert len(sheets) == 1
        assert any("sub.sch" in w for w in warnings)


@pytest.mark.kicad_cli
class TestRescueEndToEnd:
    @pytest.fixture
    def rescued(self, tiny_project, kicad_cli_path):
        return rescue_project(tiny_project, cli_path=str(kicad_cli_path), verify=False)

    def test_writes_a_schematic_per_sheet(self, rescued, tiny_project):
        assert (tiny_project / "tiny.kicad_sch").exists()
        assert (tiny_project / "sub.kicad_sch").exists()

    def test_writes_a_project_file(self, rescued, tiny_project):
        assert (tiny_project / "tiny.kicad_pro").exists()

    def test_converts_the_cache_library(self, rescued, tiny_project):
        assert (tiny_project / "tiny-cache.kicad_sym").exists()

    def test_archives_legacy_sources_out_of_kicads_reach(self, rescued, tiny_project):
        # Left in place, KiCad would happily reopen the .sch and stub it again.
        assert not (tiny_project / "tiny.sch").exists()
        assert (tiny_project / "legacy" / "tiny.sch").exists()
        assert (tiny_project / "legacy" / "tiny-cache.lib").exists()

    def test_no_warnings_on_a_clean_project(self, rescued):
        assert rescued.warnings == []

    def test_reports_symbol_count(self, rescued):
        assert rescued.symbol_count == 3
        assert rescued.total_components == 4

    def test_refuses_to_overwrite_without_permission(self, tiny_project, kicad_cli_path):
        from kicad_revive.errors import OutputExists

        (tiny_project / "tiny.kicad_sch").write_text("existing", encoding="utf-8")
        with pytest.raises(OutputExists):
            rescue_project(tiny_project, cli_path=str(kicad_cli_path), verify=False)

    def test_out_dir_leaves_the_original_untouched(self, tiny_project, tmp_path, kicad_cli_path):
        target = tmp_path / "copy"
        rescue_project(
            tiny_project, cli_path=str(kicad_cli_path), out_dir=target, verify=False
        )
        assert (tiny_project / "tiny.sch").exists(), "source project must not be modified"
        assert (target / "tiny.kicad_sch").exists()

    def test_output_is_reproducible(self, tiny_project, tmp_path, kicad_cli_path):
        first = tmp_path / "a"
        second = tmp_path / "b"
        for target in (first, second):
            rescue_project(
                tiny_project, cli_path=str(kicad_cli_path), out_dir=target, verify=False
            )
        assert (first / "tiny.kicad_sch").read_bytes() == (second / "tiny.kicad_sch").read_bytes()


@pytest.mark.kicad_cli
class TestRescueLoadsInKicad:
    def test_kicad_can_export_a_netlist_from_the_result(
        self, tiny_project, kicad_cli_path, tmp_path
    ):
        """The real acceptance test: KiCad itself must be able to read it."""
        from kicad_revive import kicad_cli

        rescue_project(tiny_project, cli_path=str(kicad_cli_path), verify=False)
        netlist = tmp_path / "out.net"
        kicad_cli.export_netlist(kicad_cli_path, tiny_project / "tiny.kicad_sch", netlist)

        text = netlist.read_text(encoding="utf-8", errors="replace")
        # A schematic KiCad cannot really read still exports a netlist -- just
        # an empty one. That is exactly the silent failure this tool exists to
        # work around, so assert on content, not on exit status.
        assert '(ref "R1")' in text
        assert '(ref "C1")' in text
        assert '(ref "R2")' in text, "hierarchical sub-sheet symbol missing"

    def test_no_legacy_project_has_zero_components(self, tiny_project, kicad_cli_path, tmp_path):
        """Guards the premise: KiCad really cannot read the legacy input."""
        from kicad_revive import kicad_cli
        from kicad_revive.errors import KicadCliNotFound

        netlist = tmp_path / "legacy.net"
        try:
            kicad_cli.export_netlist(kicad_cli_path, tiny_project / "tiny.sch", netlist)
        except KicadCliNotFound:
            pytest.skip("this KiCad refuses legacy schematics outright")
        text = netlist.read_text(encoding="utf-8", errors="replace")
        if '(ref "R1")' in text:
            pytest.skip("this KiCad can read legacy schematics; conversion is optional here")


class TestErrors:
    def test_directory_without_schematics_raises(self, tmp_path):
        with pytest.raises(NotLegacyFormat):
            rescue_project(tmp_path)


@pytest.mark.kicad_cli
class TestSymbolLibraryFormatMatching:
    """Regression: the embedded symbols must match the target KiCad's format.

    Symbol geometry is produced by kicad-cli, so a stale ``.kicad_sym`` left by
    a different KiCad version -- or a hard-coded schematic format version --
    puts symbols in the file that the target KiCad's parser rejects. That
    surfaces only as "Failed to load schematic", with no indication of cause.
    """

    def test_a_stale_kicad_sym_is_regenerated_not_reused(self, tiny_project, kicad_cli_path):
        from kicad_revive import kicad_cli

        stale = tiny_project / "tiny-cache.kicad_sym"
        stale.write_text("(kicad_symbol_lib (version 19700101) (generator stale))", encoding="utf-8")
        rescue_project(tiny_project, cli_path=str(kicad_cli_path), verify=False, overwrite=True)
        assert "19700101" not in stale.read_text(encoding="utf-8")
        assert str(kicad_cli.major_version(kicad_cli_path)) in stale.read_text(encoding="utf-8")

    def test_conversion_failure_is_reported_not_silently_accepted(self, tmp_path, kicad_cli_path):
        from kicad_revive import kicad_cli
        from kicad_revive.errors import SymbolLibraryConversionFailed

        broken = tmp_path / "broken.lib"
        broken.write_text("this is not a symbol library", encoding="utf-8")
        destination = tmp_path / "broken.kicad_sym"
        destination.write_text("(kicad_symbol_lib)", encoding="utf-8")  # stale leftover

        with pytest.raises(SymbolLibraryConversionFailed):
            kicad_cli.upgrade_symbol_library(kicad_cli_path, broken, destination)

    def test_schematic_declares_the_format_the_cli_writes(self, tiny_project, kicad_cli_path):
        from kicad_revive import kicad_cli

        result = rescue_project(tiny_project, cli_path=str(kicad_cli_path), verify=False)
        major = kicad_cli.major_version(kicad_cli_path)
        expected = kicad_cli._SCHEMATIC_FORMAT_VERSIONS.get(major)
        if expected is None:
            pytest.skip(f"unknown KiCad major version {major}")
        assert result.format_version == expected
        assert f"(version {expected})" in (tiny_project / "tiny.kicad_sch").read_text(
            encoding="utf-8"
        )
