"""Small shapely helpers for resolution geometry evidence."""

from shapely import from_wkt
from shapely.geometry.base import BaseGeometry


def parse_wkt(wkt: str) -> BaseGeometry:
    return from_wkt(wkt)


def iou(a: BaseGeometry, b: BaseGeometry) -> float:
    """Intersection-over-union of two geometries; 0.0 when union is empty."""
    union = a.union(b).area
    if union <= 0:
        return 0.0
    return a.intersection(b).area / union
