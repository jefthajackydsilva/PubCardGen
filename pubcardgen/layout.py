"""Coordinates measured from the vector geometry of S-21_E.pdf (11/23 edition).

All values are in PDF points with the origin at the bottom-left of the page,
matching ReportLab's canvas coordinate system.
"""

from __future__ import annotations

PAGE_WIDTH = 595.2
PAGE_HEIGHT = 841.9

FONT = "Helvetica"

# Printed checkbox squares, measured from the rendered template.
HEADER_BOX_SIZE = 8.6
TABLE_BOX_SIZE = 10.8
CHECK_SCALE = 0.8

BODY_SIZE = 10.0
REMARKS_SIZE = 8.0
MIN_REMARKS_SIZE = 5.0

DATE_FORMAT = "%d %b %Y"

# --- header fields -------------------------------------------------------
NAME_X = 55.0
NAME_BASELINE = 764.6
NAME_MAX_WIDTH = 325.0

DOB_X = 95.0
DOB_BASELINE = 748.5

BAPTISM_X = 112.0
BAPTISM_BASELINE = 732.3

# --- header check box centres --------------------------------------------
CHECK_MALE = (389.19, 751.77)
CHECK_FEMALE = (490.56, 751.77)
CHECK_OTHER_SHEEP = (389.19, 735.59)
CHECK_ANOINTED = (490.56, 735.59)
CHECK_ELDER = (22.06, 719.40)
CHECK_MINISTERIAL_SERVANT = (85.56, 719.40)
CHECK_REGULAR_PIONEER = (221.06, 719.40)
CHECK_SPECIAL_PIONEER = (341.31, 719.40)
CHECK_FIELD_MISSIONARY = (459.81, 719.40)

# --- service year label ---------------------------------------------------
SERVICE_YEAR_CENTRE_X = 59.45
SERVICE_YEAR_BASELINE = 657.5
SERVICE_YEAR_SIZE = 9.5

# --- table ----------------------------------------------------------------
# Vertical rules at x = 101.4, 172.0, 242.6, 313.1, 383.7 between the outer edges.
COLUMN_EDGES = (17.5, 101.4, 172.0, 242.6, 313.1, 383.7, 577.7)

SHARED_CHECK_X = 136.56
BIBLE_STUDIES_CENTRE_X = 207.3
AUX_PIONEER_CHECK_X = 277.75
HOURS_CENTRE_X = 348.4
REMARKS_LEFT_X = 388.0
REMARKS_MAX_WIDTH = COLUMN_EDGES[6] - REMARKS_LEFT_X - 4.0

# Horizontal rules bounding the twelve month rows, as distance from the page top.
_ROW_EDGES_FROM_TOP = (
    199.8,
    219.8,
    239.6,
    259.4,
    279.2,
    299.2,
    319.0,
    338.8,
    358.6,
    378.5,
    398.3,
    418.2,
    438.7,
)

_TOTAL_ROW_FROM_TOP = (438.5, 458.1)
TOTAL_HOURS_CENTRE_X = 348.7


def _row_centre(top: float, bottom: float) -> float:
    return PAGE_HEIGHT - (top + bottom) / 2.0


ROW_CENTRES: tuple[float, ...] = tuple(
    _row_centre(_ROW_EDGES_FROM_TOP[i], _ROW_EDGES_FROM_TOP[i + 1]) for i in range(12)
)

TOTAL_ROW_CENTRE = _row_centre(*_TOTAL_ROW_FROM_TOP)


def baseline(centre_y: float, font_size: float) -> float:
    """Baseline that vertically centres text of the given size on ``centre_y``."""
    return centre_y - font_size * 0.35
