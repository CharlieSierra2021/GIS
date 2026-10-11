import json
from pathlib import Path

import httpx
import pytest

from connectors.arcgis import ArcGISFeatureServiceConnector
from connectors.registry import Dataset, Permissions
from resolution.arcgis_source import ArcGISParcelSource, ParcelFieldMap
from resolution.intake import IntakeKind, IntakeRequest
from resolution.models import ResolutionStatus
from resolution.resolver import ParcelResolver

FIXTURES = (
    Path(__file__).resolve().parents[1] / "connectors" / "fixtures"
)
META = json.loads((FIXTURES / "arcgis_layer_meta.json").read_text(encoding="utf-8"))
PARCELS = json.loads(
    (FIXTURES / "arcgis_parcels_page.json").read_text(encoding="utf-8")
)
ENDPOINT = "https://gis.example.com/arcgis/rest/services/parcels/FeatureServer/0"


def _source(handler=None, seen=None):
    def default(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            if seen is not None:
                seen.update(dict(request.url.params))
            return httpx.Response(200, json=PARCELS)
        return httpx.Response(200, json=META)

    dataset = Dataset(
        id="basemap_parcels",
        provider="volusia_county_gis",
        access_type="arcgis_query",
        endpoint=ENDPOINT,
        permissions=Permissions(query=True),
        status="implementation-ready",
        tasks=[],
    )
    conn = ArcGISFeatureServiceConnector(
        "volusia_county_gis",
        dataset,
        ENDPOINT,
        client=httpx.Client(
            transport=httpx.MockTransport(handler or default)
        ),
        sleep=lambda _: None,
    )
    return ArcGISParcelSource(conn, field_map=ParcelFieldMap())


def test_by_parcel_id_where_clause() -> None:
    seen = {}
    cands = _source(seen=seen).by_parcel_id("P-001")
    assert seen["where"] == "PARID = 'P-001'"
    assert len(cands) == 1
    assert cands[0].parcel_id == "P-001"


def test_by_parcel_id_escapes_quote() -> None:
    seen = {}
    _source(seen=seen).by_parcel_id("O'BRIEN-12")
    assert seen["where"] == "PARID = 'O''BRIEN-12'"


def test_by_parcel_id_rejects_injection() -> None:
    with pytest.raises(ValueError):
        _source().by_parcel_id("X'; DROP TABLE parcels;--")


def test_by_address_returns_all_units() -> None:
    cands = _source().by_address("500 OCEAN BLVD")
    assert {c.parcel_id for c in cands} == {"C-101", "C-102"}
    assert all(c.is_condo_unit for c in cands)
    assert {c.unit for c in cands} == {"101", "102"}


def test_by_address_filters_like_mismatch() -> None:
    # Service returns a non-matching situs for the LIKE prefix; it is dropped.
    payload = json.loads(json.dumps(PARCELS))
    payload["features"].append(
        {
            "attributes": {
                "OBJECTID": 204,
                "PARID": "X-1",
                "SITUS": "500 SHORE DR",
                "UNIT": None,
            },
            "geometry": PARCELS["features"][0]["geometry"],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json=META)

    cands = _source(handler=handler).by_address("500 OCEAN BLVD")
    assert {c.parcel_id for c in cands} == {"C-101", "C-102"}


def test_spatial_queries_return_candidates_with_geometry() -> None:
    seen = {}
    src = _source(seen=seen)
    cands = src.intersecting("POLYGON ((-81.05 29.2, -81.04 29.2, -81.04 29.21, -81.05 29.21, -81.05 29.2))")
    assert cands and all(c.geometry_wkt for c in cands)
    assert seen["spatialRel"] == "esriSpatialRelIntersects"

    cands2 = src.containing_point(-81.045, 29.205)
    assert cands2
    point_geom = json.loads(seen["geometry"])
    assert point_geom["x"] == -81.045


def test_resolver_composes_with_arcgis_source() -> None:
    resolver = ParcelResolver(_source())
    decision = resolver.resolve(
        IntakeRequest(
            kind=IntakeKind.ADDRESS, address="500 Ocean Boulevard Unit 102"
        )
    )
    assert decision.status == ResolutionStatus.RESOLVED
    assert decision.parcel_id == "C-102"
