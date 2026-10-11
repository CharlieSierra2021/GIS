import json
from pathlib import Path

import httpx
import pytest
from shapely import from_wkt

from connectors.contract import ConnectorError, FailureClass
from connectors.evidence import RegistryEvidenceFetcher
from connectors.factory import ConnectorFactory
from connectors.registry import load_registry

FIXTURES = Path(__file__).with_name("fixtures")
META = json.loads((FIXTURES / "arcgis_layer_meta.json").read_text(encoding="utf-8"))
PAGE = json.loads((FIXTURES / "arcgis_query_page.json").read_text(encoding="utf-8"))
ENDPOINT = "https://gis.example.com/arcgis/rest/services/parcels/FeatureServer/0"
PARCEL_WKT = "POLYGON ((-81.05 29.2, -81.04 29.2, -81.04 29.21, -81.05 29.21, -81.05 29.2))"


def _fetcher(handler, dataset_id="fdep_contam", overrides=None, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    factory = ConnectorFactory(
        load_registry(),
        client=client,
        endpoint_overrides=overrides or {dataset_id: ENDPOINT},
    )
    return RegistryEvidenceFetcher(factory, **kw)


def _ok_handler(page=PAGE):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=page)
        return httpx.Response(200, json=META)

    return handler


def test_fetch_sends_geometry_intersects() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            seen.update(dict(request.url.params))
            return httpx.Response(200, json=PAGE)
        return httpx.Response(200, json=META)

    page = _fetcher(handler).fetch("fdep_contam", PARCEL_WKT, "intersects", None)
    assert len(page.features) == 2
    assert json.loads(seen["geometry"])["rings"]
    assert seen["spatialRel"] == "esriSpatialRelIntersects"


def test_buffer_enlarges_query_geometry() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            seen.update(dict(request.url.params))
            return httpx.Response(200, json=PAGE)
        return httpx.Response(200, json=META)

    _fetcher(handler).fetch("fdep_contam", PARCEL_WKT, "intersects", 500)
    parcel = from_wkt(PARCEL_WKT)
    sent = from_wkt(
        "POLYGON (("
        + ", ".join(
            f"{x} {y}" for x, y in json.loads(seen["geometry"])["rings"][0]
        )
        + "))"
    )
    assert sent.bounds[0] < parcel.bounds[0] - 0.001  # ~100m+ westward expansion
    assert sent.area > parcel.area


def test_pagination_concatenates_pages() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            params = dict(request.url.params)
            calls.append(int(params.get("resultOffset", 0)))
            first = len(calls) == 1
            payload = dict(PAGE)
            payload["features"] = PAGE["features"][:1] if first else PAGE["features"][1:]
            payload["exceededTransferLimit"] = first
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json=META)

    page = _fetcher(handler).fetch("fdep_contam", PARCEL_WKT, "intersects", None)
    assert len(page.features) == 2
    assert calls == [0, 1]
    assert page.exceeded_limit is False


def test_max_pages_sets_exceeded_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(
                200, json={**PAGE, "exceededTransferLimit": True}
            )
        return httpx.Response(200, json=META)

    page = _fetcher(handler, max_pages=2).fetch(
        "fdep_contam", PARCEL_WKT, "intersects", None
    )
    assert page.exceeded_limit is True
    assert len(page.features) == 4  # 2 pages x 2 features


def test_connector_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    with pytest.raises(ConnectorError) as exc:
        _fetcher(handler).fetch("fdep_contam", PARCEL_WKT, "intersects", None)
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED


def test_registry_denied_dataset_raises() -> None:
    fetcher = _fetcher(_ok_handler(), overrides={"utility_service": ENDPOINT})
    with pytest.raises(ConnectorError) as exc:
        fetcher.fetch("utility_service", PARCEL_WKT, "intersects", None)
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED
