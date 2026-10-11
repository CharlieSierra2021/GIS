import json
from pathlib import Path

import httpx
import pytest

from connectors.arcgis import ArcGISFeatureServiceConnector
from connectors.contract import ConnectorError, FailureClass, QueryRequest
from connectors.registry import load_registry

FIXTURES = Path(__file__).resolve().parents[1] / "connectors" / "fixtures"
META = json.loads((FIXTURES / "arcgis_layer_meta.json").read_text(encoding="utf-8"))
PAGE = json.loads((FIXTURES / "arcgis_query_page.json").read_text(encoding="utf-8"))
ENDPOINT = "https://gis.example.com/arcgis/rest/services/parcels/FeatureServer/0"


def _client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json=PAGE)
        return httpx.Response(200, json=META)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.acceptance
def test_fl_tst_05_describe_query_roundtrip() -> None:
    registry = load_registry()
    dataset = registry.dataset("basemap_parcels")
    conn = ArcGISFeatureServiceConnector(
        "volusia_county_gis",
        dataset,
        ENDPOINT,
        client=_client(),
        sleep=lambda _: None,
    )

    desc = conn.describe()
    assert desc.dataset_id == "basemap_parcels"
    assert desc.fingerprint

    page = conn.query(QueryRequest(where="1=1"))
    assert len(page.features) == 2
    for feat in page.features:
        assert feat.provenance.dataset_id == "basemap_parcels"
        assert feat.provenance.retrieved_at is not None
        assert feat.key


@pytest.mark.acceptance
def test_fl_tst_05_null_query_right_denied() -> None:
    registry = load_registry()
    dataset = registry.dataset("official_records")
    assert dataset.permissions.query is None  # null = denied (REQ-REG-02)
    conn = ArcGISFeatureServiceConnector(
        "volusia_clerk",
        dataset,
        "https://clerk.example.com/records",
        client=_client(),
        sleep=lambda _: None,
    )
    with pytest.raises(ConnectorError) as exc:
        conn.query(QueryRequest())
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED
