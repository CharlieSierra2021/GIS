"""Measurement geometry — ICD §9.

Screening operates on WGS84 geometries; measurement (distances, buffers)
is done in EPSG:3087 (Florida GDL Albers), the statewide equal-area
projection, via pyproj. Distances and buffered areas surfaced in evidence
are true metres, not approximations.
"""

import shapely
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry

_EPSG_MEASURE = "EPSG:3087"

_to_measure = Transformer.from_crs(
    "EPSG:4326", _EPSG_MEASURE, always_xy=True
).transform
_from_measure = Transformer.from_crs(
    _EPSG_MEASURE, "EPSG:4326", always_xy=True
).transform


def to_measure(geom: BaseGeometry) -> BaseGeometry:
    """Project a WGS84 (EPSG:4326) geometry into EPSG:3087 metres."""
    return shapely.transform(geom, _to_measure, interleaved=False)


def from_measure(geom: BaseGeometry) -> BaseGeometry:
    """Unproject an EPSG:3087 geometry back to WGS84."""
    return shapely.transform(geom, _from_measure, interleaved=False)


def distance_m(a: BaseGeometry, b: BaseGeometry) -> float:
    """True a.distance(b) in metres, measured in EPSG:3087."""
    return to_measure(a).distance(to_measure(b))


def buffer_m(geom: BaseGeometry, metres: float) -> BaseGeometry:
    """Metric buffer around a WGS84 geometry, returned in WGS84."""
    return from_measure(to_measure(geom).buffer(metres))


# Deprecated aliases — kept so callers written against the M6
# equirectangular helpers keep working; use distance_m / buffer_m instead.
approx_distance_m = distance_m
buffer_approx = buffer_m
