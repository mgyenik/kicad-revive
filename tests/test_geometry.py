"""Tests for the legacy/modern coordinate conversions.

These cover the three rules that fail *silently* -- output that loads, renders,
and looks plausible while being wrong. Each test names the real-world evidence
that established the rule, so a future change that breaks one is recognisable
as a regression rather than a style difference.
"""

from __future__ import annotations

import pytest

from kicad_revive.geometry import (
    MIL_TO_MM,
    ORIENT_TABLE,
    field_angle,
    label_angle,
    label_justify,
    mm,
    orientation,
    transform_field,
)


class TestUnits:
    def test_legacy_a3_dimensions_are_rounded_mils(self):
        # A3 is 420 x 297 mm, but the legacy format records it in whole mils as
        # 16535 x 11693, which is 419.989 x 297.0022 mm. The paper size is
        # therefore emitted by *name* rather than as a User size, so the sheet
        # comes out exactly A3 instead of 11um short.
        assert mm("16535") == "419.989"
        assert mm("11693") == "297.0022"

    def test_conversion_factor(self):
        assert MIL_TO_MM == 0.0254

    def test_round_numbers_are_exact(self):
        assert mm("1000") == "25.4"
        assert mm("0") == "0"

    def test_zero_never_renders_as_negative_zero(self):
        assert mm(-0.0) == "0"
        assert not mm("-0").startswith("-")



class TestOrientation:
    def test_legacy_identity_is_not_the_maths_identity(self):
        # The legacy identity flips Y because the matrix maps library space
        # (Y up) to sheet space (Y down). Assuming (1,0,0,1) is the identity
        # mirrors every symbol vertically.
        assert orientation((1, 0, 0, -1)) == (0, None)
        assert orientation((1, 0, 0, 1)) == (0, "x")

    @pytest.mark.parametrize(
        ("matrix", "expected"),
        [
            ((1, 0, 0, -1), (0, None)),
            ((0, -1, -1, 0), (90, None)),
            ((-1, 0, 0, 1), (180, None)),
            ((0, 1, 1, 0), (270, None)),
            ((1, 0, 0, 1), (0, "x")),
            ((0, -1, 1, 0), (90, "x")),
            ((-1, 0, 0, -1), (0, "y")),
            ((0, 1, -1, 0), (90, "y")),
        ],
    )
    def test_all_eight_orientations(self, matrix, expected):
        assert orientation(matrix) == expected

    def test_table_is_exactly_the_eight_legal_orientations(self):
        assert len(ORIENT_TABLE) == 8

    def test_unknown_matrix_raises_rather_than_guessing(self):
        with pytest.raises(KeyError):
            orientation((1, 1, 1, 1))


class TestFieldPlacement:
    """Field offsets are in library coordinates (Y up), not sheet coordinates."""

    def test_unrotated_symbol_still_flips_y(self):
        # From the reference project: C4 sits at (11300, 1000) with its
        # Reference stored at y=1046 -- below the symbol in file order -- yet
        # KiCad 5.1 renders it *above*. Copying the position through unchanged
        # swaps every reference/value pair vertically.
        x, y = transform_field((1, 0, 0, -1), (11300.0, 1000.0), (11415.0, 1046.0))
        assert x == pytest.approx(11415.0)
        assert y == pytest.approx(954.0)  # above the symbol

    def test_value_field_lands_below_when_reference_is_above(self):
        ref = transform_field((1, 0, 0, -1), (11300.0, 1000.0), (11415.0, 1046.0))
        val = transform_field((1, 0, 0, -1), (11300.0, 1000.0), (11415.0, 955.0))
        assert ref[1] < val[1], "reference should render above value"

    def test_rotated_symbol_maps_offset_sideways(self):
        # A GND label on a 90-degree-rotated symbol, stored 173mil "above" the
        # symbol, must render 173mil to its right.
        x, y = transform_field((0, -1, -1, 0), (14850.0, 1750.0), (14855.0, 1577.0))
        assert x == pytest.approx(14850.0 + 173.0)
        assert y == pytest.approx(1750.0 - 5.0)

    def test_mounting_hole_field_moves_above_when_rotated(self):
        # H1: symbol at (14750,1750), Reference stored at (14987,1753) -- i.e.
        # 237mil to the right -- renders 237mil above once rotated 90 degrees.
        x, y = transform_field((0, -1, -1, 0), (14750.0, 1750.0), (14987.0, 1753.0))
        assert y == pytest.approx(1750.0 - 237.0)
        assert x == pytest.approx(14750.0 - 3.0)

    def test_field_at_symbol_origin_is_unmoved(self):
        for matrix in ORIENT_TABLE:
            assert transform_field(matrix, (100.0, 200.0), (100.0, 200.0)) == (100.0, 200.0)


class TestFieldAngle:
    """Position is absolute; angle is relative to the symbol's own rotation."""

    def test_angle_is_not_rotated_by_the_symbol(self):
        # KiCad adds the symbol's rotation to the property angle when
        # rendering. Rotating it here as well turns every field on a rotated
        # symbol through 90 degrees.
        assert field_angle("H") == 0
        assert field_angle("V") == 90


class TestLabels:
    def test_global_label_is_anchored_at_the_opposite_end(self):
        # Verified geometrically: a GLabel anchored at (4100,4050) has its wire
        # running right to (4200,4050), so the body must sit to the left.
        assert label_angle("GLabel", 0) == 180
        assert label_angle("GLabel", 2) == 0

    def test_plain_label_reads_in_the_natural_direction(self):
        assert label_angle("Label", 0) == 0
        assert label_angle("Label", 2) == 180

    def test_hierarchical_labels_follow_global_labels(self):
        assert label_angle("HLabel", 0) == label_angle("GLabel", 0)

    def test_notes_are_bottom_left_anchored(self):
        # Modern (text ...) defaults to centred, which shifts long headings
        # left by half their width and reads like a scaling bug.
        hjustify, vjustify = label_justify("Notes", 0)
        assert (hjustify, vjustify) == ("L", "B")

    def test_global_labels_take_no_vertical_justification(self):
        hjustify, vjustify = label_justify("GLabel", 180)
        assert hjustify == "R"
        assert vjustify is None

    def test_right_to_left_text_is_right_justified(self):
        assert label_justify("Label", 180)[0] == "R"
