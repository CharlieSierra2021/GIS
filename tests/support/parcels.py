"""Shared toy county: two single-family parcels and a two-unit condo
building at 500 OCEAN BLVD (parent C-000, units C-101/C-102 sharing the
footprint), plus lone unit U-1 at 700 CANAL CT."""

from shapely.geometry import box

from resolution.fixtures import InMemoryParcelSource
from resolution.models import ParcelCandidate


def _wkt(minx, miny, maxx, maxy) -> str:
    return box(minx, miny, maxx, maxy).wkt


PARCELS = [
    ParcelCandidate(
        parcel_id="P-001",
        situs_address="123 MAIN ST",
        geometry_wkt=_wkt(0, 0, 10, 10),
    ),
    ParcelCandidate(
        parcel_id="P-002",
        situs_address="456 OAK AVE",
        geometry_wkt=_wkt(20, 0, 30, 10),
    ),
    ParcelCandidate(
        parcel_id="C-000",
        situs_address="500 OCEAN BLVD",
        geometry_wkt=_wkt(40, 0, 50, 10),
    ),
    ParcelCandidate(
        parcel_id="U-1",
        situs_address="700 CANAL CT",
        unit="1",
        geometry_wkt=_wkt(60, 0, 70, 10),
        is_condo_unit=True,
    ),
    ParcelCandidate(
        parcel_id="C-101",
        situs_address="500 OCEAN BLVD",
        unit="101",
        geometry_wkt=_wkt(40, 0, 50, 10),
        is_condo_unit=True,
        parent_parcel_id="C-000",
    ),
    ParcelCandidate(
        parcel_id="C-102",
        situs_address="500 OCEAN BLVD",
        unit="102",
        geometry_wkt=_wkt(40, 0, 50, 10),
        is_condo_unit=True,
        parent_parcel_id="C-000",
    ),
]


def build_source() -> InMemoryParcelSource:
    return InMemoryParcelSource(list(PARCELS))
