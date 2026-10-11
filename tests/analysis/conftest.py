from datetime import UTC, datetime

import pytest
from shapely.geometry import box

from connectors.contract import (
    ConnectorError,
    Feature,
    FeaturePage,
    Provenance,
)
from connectors.registry import load_registry

NOW = datetime(2025, 6, 1, tzinfo=UTC)

# Parcel in the Daytona area, roughly 1 km wide.
PARCEL_WKT = box(-81.0, 29.0, -80.99, 29.01).wkt
PARCEL_GEOM = box(-81.0, 29.0, -80.99, 29.01)


def feat(key: str, attrs: dict, wkt: str | None = None, retrieved_at=None) -> Feature:
    return Feature(
        key=key,
        attributes=attrs,
        geometry_wkt=wkt or PARCEL_WKT,
        provenance=Provenance(
            dataset_id="stub",
            source_feature_key=key,
            retrieved_at=retrieved_at or NOW,
            native_crs="EPSG:4326",
        ),
    )


def page(*features: Feature) -> FeaturePage:
    return FeaturePage(features=list(features))


class StubFetcher:
    """Records every fetch call; returns the configured FeaturePage or
    raises the configured ConnectorError per dataset id."""

    def __init__(self, pages: dict) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, dataset_id, parcel_wkt, spatial_rel, buffer_m) -> FeaturePage:
        self.calls.append(dataset_id)
        result = self.pages[dataset_id]
        if isinstance(result, ConnectorError):
            raise result
        return result


def full_pages() -> dict:
    """One non-empty page per profile dataset."""
    return {
        "nfhl_flood": page(
            feat("n1", {"FLD_ZONE": "AE", "SFHA_TF": "T"}),
            feat("n2", {"FLD_ZONE": "X", "SFHA_TF": "F"}),
        ),
        "nwi_wetlands": page(feat("w1", {"WETLAND_TYPE": "Palustrine"})),
        "ssurgo_soils": page(feat("s1", {"MUSYM": "10", "HYDRIC_RATING": "Yes"})),
        "sinkhole_reports": page(
            feat("k1", {}, "POINT (-80.98 29.005)")  # ~1 km east of parcel
        ),
        "permits": page(feat("p1", {"PERMIT_NO": "B-2024-001"})),
        "fdep_contam": page(feat("c1", {}, "POINT (-80.985 29.005)")),
        "county_flu": page(feat("f1", {"FLU": "RES"})),
        "mun_flu": page(feat("f2", {"FLU": "MUN-RES"})),
        "fdot_roads": page(
            feat("r1", {}, "LINESTRING (-80.99 29.005, -80.98 29.005)")
        ),
        "utility_service": page(feat("u1", {})),
    }


@pytest.fixture()
def granted_registry():
    """Deep copy of the real registry with query=True granted for every
    profile dataset (permits/utility_service are null in the seed)."""
    reg = load_registry().model_copy(deep=True)
    for ds_id in (
        "permits",
        "utility_service",
        "county_flu",
        "mun_flu",
        "sinkhole_reports",
        "fdep_contam",
        "fdot_roads",
    ):
        reg.dataset(ds_id).permissions.query = True
    return reg
