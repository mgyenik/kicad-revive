"""Coordinate and orientation conversion between legacy and modern KiCad.

Every subtlety in this package lives here.  Each rule below was established by
converting a real KiCad 5.1 project and diffing the rendered result against a
PDF that KiCad 5.1 itself had exported in 2020 -- not by reading KiCad's source.
The docstrings record *why*, because all three of these fail silently: the
output loads, renders, and looks plausible while being wrong.
"""

from __future__ import annotations

from typing import Optional

#: Legacy schematics are dimensioned in mils (1/1000 inch); modern ones in mm.
MIL_TO_MM = 0.0254

Matrix = tuple[int, int, int, int]

#: Legacy orientation matrix ``(A, B, C, D)`` -> ``(rotation_degrees, mirror_axis)``.
#:
#: The legacy identity is ``(1, 0, 0, -1)`` rather than ``(1, 0, 0, 1)`` because
#: the matrix maps *library* space (Y up) to *sheet* space (Y down); the sign
#: flip is that axis inversion, not a mirror.  Mirrors are therefore the
#: matrices whose determinant differs from the identity's.
ORIENT_TABLE: dict[Matrix, tuple[int, Optional[str]]] = {
    (1, 0, 0, -1): (0, None),
    (0, -1, -1, 0): (90, None),
    (-1, 0, 0, 1): (180, None),
    (0, 1, 1, 0): (270, None),
    (1, 0, 0, 1): (0, "x"),
    (0, -1, 1, 0): (90, "x"),
    (-1, 0, 0, -1): (0, "y"),
    (0, 1, -1, 0): (90, "y"),
}

#: Legacy label shape name -> modern shape token.
SHAPE_TABLE = {
    "Input": "input",
    "Output": "output",
    "BiDi": "bidirectional",
    "3State": "tri_state",
    "UnSpc": "passive",
}

#: Legacy sheet-pin form letter -> legacy shape name.
SHEET_PIN_FORM = {"I": "Input", "O": "Output", "B": "BiDi", "T": "3State", "U": "UnSpc"}

#: Legacy sheet-pin side letter -> modern pin angle in degrees.
SHEET_PIN_ANGLE = {"L": 0, "R": 180, "T": 270, "B": 90}


def mm(mils: float | str) -> str:
    """Format a legacy mil value as millimetres, at KiCad's precision."""
    value = round(float(mils) * MIL_TO_MM, 6)
    if value == 0:
        value = 0.0  # normalise -0.0
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


def orientation(matrix: Matrix) -> tuple[int, Optional[str]]:
    """Resolve a legacy orientation matrix to ``(angle, mirror)``.

    Raises :class:`KeyError` for matrices outside the eight legal orientations;
    callers are expected to warn and fall back rather than guess.
    """
    return ORIENT_TABLE[matrix]


def transform_field(
    matrix: Matrix,
    symbol_xy: tuple[float, float],
    field_xy: tuple[float, float],
) -> tuple[float, float]:
    """Map a legacy field position into modern absolute sheet coordinates.

    A legacy field position is the symbol origin plus an offset expressed in
    **library** coordinates (Y up).  The orientation matrix is precisely what
    maps library space to sheet space (Y down) -- which is why the identity is
    ``(1, 0, 0, -1)``.  The modern format stores the final sheet position, so
    the matrix has to be applied here.

    Copying legacy field positions across unchanged is the single most damaging
    mistake available: it misplaces every field on every rotated symbol, *and*
    silently swaps each symbol's reference and value vertically -- including on
    unrotated symbols, because even the identity matrix inverts Y.

    Established from the reference project: ``C4``'s Reference is stored below
    its Value in the file yet renders above it, and a 90-degree-rotated ``GND``
    label stored 173mil "above" its symbol renders 173mil to its right.
    """
    a, b, c, d = matrix
    sx, sy = symbol_xy
    dx = field_xy[0] - sx
    dy = field_xy[1] - sy
    return sx + a * dx + b * dy, sy + c * dx + d * dy


def field_angle(orient: str) -> int:
    """Modern angle for a legacy field orientation letter (``H`` or ``V``).

    Note the asymmetry with :func:`transform_field`: KiCad treats a property's
    *position* as absolute but its *angle* as relative to the symbol's own
    rotation, and adds the two when rendering.  So positions must be
    transformed and angles must not.  Rotating the angle here as well makes
    every field on a rotated symbol read at 90 degrees to the original.
    """
    return 0 if orient == "H" else 90


def label_angle(kind: str, legacy_orient: int) -> int:
    """Modern angle for a legacy text/label orientation index (0-3).

    Plain text and labels extend away from their anchor in the reading
    direction.  Global and hierarchical labels are anchored at the *connecting*
    end instead, so their body extends the opposite way and the modern
    equivalent is rotated 180 degrees.

    Established geometrically rather than assumed: in the reference project a
    ``Text GLabel`` anchored at ``(4100, 4050)`` has its wire running right to
    ``(4200, 4050)``, so the label body must sit to the *left* of the anchor.
    """
    angle = (legacy_orient % 4) * 90
    if kind in ("GLabel", "HLabel"):
        angle = (angle + 180) % 360
    return angle


def label_justify(kind: str, angle: int) -> tuple[str, Optional[str]]:
    """Return ``(hjustify, vjustify)`` letters for a converted label.

    Legacy text is anchored bottom-left and drawn up and to the right; modern
    ``(text ...)`` defaults to centred, so omitting justification shifts every
    string left by half its width -- subtly for short labels and glaringly for
    long headings, which reads like a scaling error rather than a text one.

    Global and hierarchical labels sit inside a shape outline that already
    centres them vertically, so they take horizontal justification only.
    """
    hjustify = "L" if angle in (0, 90) else "R"
    vjustify = "B" if kind in ("Notes", "Label") else None
    return hjustify, vjustify
