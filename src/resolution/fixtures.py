"""In-memory ParcelSource for tests and local development."""

from shapely import from_wkt
from shapely.geometry import Point

from resolution.intake import normalize_address
from resolution.models import ParcelCandidate


class InMemoryParcelSource:
    def __init__(self, candidates: list[ParcelCandidate]) -> None:
        self._candidates = list(candidates)
        self._address_index: dict[str, list[ParcelCandidate]] = {}
        for cand in self._candidates:
            if cand.situs_address:
                key = normalize_address(cand.situs_address).street
                self._address_index.setdefault(key, []).append(cand)

    def by_parcel_id(self, pid: str) -> list[ParcelCandidate]:
        return [c for c in self._candidates if c.parcel_id == pid]

    def by_address(self, street_normalized: str) -> list[ParcelCandidate]:
        return list(self._address_index.get(street_normalized, []))

    def intersecting(self, geometry_wkt: str) -> list[ParcelCandidate]:
        geom = from_wkt(geometry_wkt)
        return [
            c
            for c in self._candidates
            if c.geometry_wkt and from_wkt(c.geometry_wkt).intersects(geom)
        ]

    def containing_point(self, x: float, y: float) -> list[ParcelCandidate]:
        pt = Point(x, y)
        return [
            c
            for c in self._candidates
            if c.geometry_wkt and from_wkt(c.geometry_wkt).contains(pt)
        ]
