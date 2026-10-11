"""Approximate distance for screening buffers.

Screening operates on WGS84 geometries. Proper measurement reprojection
(EPSG:3087 Florida GDL Albers) arrives with pyproj in a later milestone; for
now distances are computed on an equirectangular approximation at the
parcel's latitude — adequate for hundred-metre screening buffers, and
labelled approximate everywhere it surfaces.
"""

import math

from shapely import affinity
from shapely.geometry.base import BaseGeometry

_M_PER_DEG_LAT = 111_320.0


def approx_distance_m(a: BaseGeometry, b: BaseGeometry) -> float:
    """Approximate a.distance(b) in metres via equirectangular scaling."""
    lat = a.centroid.y
    xfact = _M_PER_DEG_LAT * math.cos(math.radians(lat))
    a_m = affinity.scale(a, xfact=xfact, yfact=_M_PER_DEG_LAT, origin=(0, 0))
    b_m = affinity.scale(b, xfact=xfact, yfact=_M_PER_DEG_LAT, origin=(0, 0))
    return a_m.distance(b_m)
