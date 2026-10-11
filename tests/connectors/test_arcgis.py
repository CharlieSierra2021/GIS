import json
from pathlib import Path

import httpx
import pytest
from shapely import from_wkt

from connectors.arcgis import ArcGISFeatureServiceConnector
from connectors.contract import ConnectorError, FailureClass, QueryRequest
from connectors.registry import Dataset, Permissions

FIXTURES = Path(__file__).with_name("fixtures")
META = json.loads((FIXTURES / "arcgis_layer_meta.json").read_text(encoding="utf-8"))
PAGE = json.loads((FIXTURES / "arcgis_query_page.json").read_text(encoding="utf-8"))

ENDPOINT = "https://gis.example.com/arcgis/rest/services/parcels/FeatureServer/0"


def _dataset(query: bool | None = True) -> Dataset:
    return Dataset(
        id="basemap_parcels",
        provider="volusia_county_gis",
        access_type="arcgis_query",
        endpoint=ENDPOINT,
        permissions=Permissions(query=query),
        status="implementation-ready",
        tasks=[],
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _static_client(payload=PAGE) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json=META)

    return _client(handler)


def _connector(**kwargs) -> ArcGISFeatureServiceConnector:
    kwargs.setdefault("client", _static_client())
    kwargs.setdefault("sleep", lambda _: None)
    return ArcGISFeatureServiceConnector(
        "volusia_county_gis", _dataset(), ENDPOINT, **kwargs
    )


def test_describe_maps_metadata() -> None:
    desc = _connector().describe()
    assert desc.layer_id == 0
    assert desc.layer_name == "Parcels"
    assert desc.native_crs == "EPSG:2881"
    assert desc.max_record_count == 1000
    assert desc.supports_pagination is True
    assert [f.name for f in desc.fields] == ["OBJECTID", "PARID", "SITUS", "OWNER"]
    assert desc.fields[1].nullable is False
    assert len(desc.fingerprint) == 64


def test_query_parses_polygon_features() -> None:
    page = _connector().query(QueryRequest(where="PARID='P-001'"))
    assert len(page.features) == 2
    feat = page.features[0]
    assert feat.key == "101"
    assert feat.attributes["PARID"] == "P-001"
    assert from_wkt(feat.geometry_wkt).geom_type == "Polygon"
    assert feat.provenance.dataset_id == "basemap_parcels"
    assert feat.provenance.retrieved_at is not None
    assert feat.provenance.observation_date is None
    assert feat.provenance.native_crs == "EPSG:2881"
    assert page.exceeded_limit is False
    assert page.next_offset is None


def test_query_parses_point_geometry() -> None:
    payload = {
        "features": [
            {
                "attributes": {"OBJECTID": 7},
                "geometry": {"x": -81.05, "y": 29.2},
            }
        ]
    }
    page = _connector(client=_static_client(payload)).query(QueryRequest())
    assert from_wkt(page.features[0].geometry_wkt).geom_type == "Point"


def test_spatial_query_sends_esri_geometry() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            seen.update(dict(request.url.params))
            return httpx.Response(200, json=PAGE)
        return httpx.Response(200, json=META)

    _connector(client=_client(handler)).query(
        QueryRequest(geometry_wkt="POINT (-81.05 29.2)")
    )
    geom = json.loads(seen["geometry"])
    assert geom["x"] == -81.05 and geom["y"] == 29.2
    assert seen["geometryType"] == "esriGeometryPoint"
    assert seen["spatialRel"] == "esriSpatialRelIntersects"
    assert seen["inSR"] == "4326"
    assert seen["outSR"] == "4326"


def test_pagination_next_offset() -> None:
    payload = {**PAGE, "exceededTransferLimit": True}
    page = _connector(client=_static_client(payload)).query(QueryRequest(offset=0))
    assert page.exceeded_limit is True
    assert page.next_offset == 2


def test_retry_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=PAGE)
        return httpx.Response(200, json=META)

    page = _connector(client=_client(handler)).query(QueryRequest())
    assert len(page.features) == 2
    assert calls["n"] >= 2


def test_exhausted_retries_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    with pytest.raises(ConnectorError) as exc:
        _connector(client=_client(handler)).query(QueryRequest())
    assert exc.value.failure_class == FailureClass.SOURCE_UNAVAILABLE


def test_http_403_permission_denied_no_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, text="forbidden")

    with pytest.raises(ConnectorError) as exc:
        _connector(client=_client(handler)).query(QueryRequest())
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED
    assert calls["n"] == 1


def test_arcgis_error_499_permission_denied() -> None:
    payload = {"error": {"code": 499, "message": "Token Required"}}

    with pytest.raises(ConnectorError) as exc:
        _connector(client=_static_client(payload)).query(QueryRequest())
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED


def test_registry_query_denied_before_network() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=META)

    conn = ArcGISFeatureServiceConnector(
        "volusia_county_gis",
        _dataset(query=None),
        ENDPOINT,
        client=_client(handler),
        sleep=lambda _: None,
    )
    with pytest.raises(ConnectorError) as exc:
        conn.query(QueryRequest())
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED
    assert calls["n"] == 0


def test_expected_fingerprint_mismatch_is_drift() -> None:
    conn = _connector(expected_fingerprint="0" * 64)
    with pytest.raises(ConnectorError) as exc:
        conn.query(QueryRequest())
    assert exc.value.failure_class == FailureClass.SCHEMA_DRIFT


def test_health_ok_and_failure() -> None:
    assert _connector().health().ok is True

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    status = _connector(client=_client(handler)).health()
    assert status.ok is False
    assert status.fingerprint is None
    assert "permission_denied" in status.detail
