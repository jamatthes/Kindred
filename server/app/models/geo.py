"""Great-circle distance, once, for everything that needs it.

Two implementations of one formula, deliberately side by side:

* :func:`haversine_m` builds a **SQL expression**, so a query can filter or order by distance
  without pulling rows into Python. `distances` (M3) uses it for the straight-line estimate it
  shows while a Distance Matrix answer is still pending (`plan/architecture.md`: "Haversine
  straight-line distance is computed instantly in SQL as a fallback").
* :func:`haversine_m_py` is the same formula in Python, used by `map-suggestions`' query-time
  grouping, which has already loaded every row it is comparing and would gain nothing from a
  round trip.

They live in one module, adjacent, because two copies of a formula in two files is how the map
and the distance chip end up disagreeing about whether something is 149 or 151 metres away.
"""

from __future__ import annotations

import math

from sqlalchemy import Float, func
from sqlalchemy.sql.elements import ColumnElement

#: IUGG mean Earth radius. The choice matters less than making it once: every caller shares it.
EARTH_RADIUS_M = 6_371_008.8


def haversine_m(
    lat1: ColumnElement | float,
    lng1: ColumnElement | float,
    lat2: ColumnElement | float,
    lng2: ColumnElement | float,
) -> ColumnElement[float]:
    """Metres between two points, as a SQL expression.

    Any argument may be a column or a literal, so "this family's home to every suggestion"
    and "these two fixed points" are the same call.
    """
    lat1_r = func.radians(lat1)
    lat2_r = func.radians(lat2)
    d_lat = func.radians(lat2 - lat1)
    d_lng = func.radians(lng2 - lng1)
    a = func.pow(func.sin(d_lat / 2), 2) + func.cos(lat1_r) * func.cos(lat2_r) * func.pow(
        func.sin(d_lng / 2), 2
    )
    return (2 * EARTH_RADIUS_M * func.asin(func.sqrt(a))).cast(Float)


def haversine_m_py(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Metres between two points, in Python. Identical formula to :func:`haversine_m`."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
