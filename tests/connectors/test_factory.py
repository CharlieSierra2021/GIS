import httpx
import pytest

from connectors.contract import ConnectorError, FailureClass
from connectors.factory import ConnectorFactory
from connectors.registry import load_registry

ENDPOINT = "https://gis.example.com/arcgis/rest/services/parcels/FeatureServer/0"


def _factory(**kwargs) -> ConnectorFactory:
    return ConnectorFactory(load_registry(), **kwargs)


def test_no_endpoint_raises_source_unavailable() -> None:
    with pytest.raises(ConnectorError) as exc:
        _factory().for_dataset("basemap_parcels")
    assert exc.value.failure_class == FailureClass.SOURCE_UNAVAILABLE
    assert "no endpoint" in exc.value.detail


def test_endpoint_override_used() -> None:
    conn = _factory(endpoint_overrides={"basemap_parcels": ENDPOINT}).for_dataset(
        "basemap_parcels"
    )
    assert conn._endpoint == ENDPOINT


def test_per_authority_override_preferred() -> None:
    overrides = {
        "mun_flu": "https://gis.example.com/county/0",
        "mun_flu:deland": "https://deland.example.com/flu/0",
    }
    factory = _factory(endpoint_overrides=overrides)
    assert (
        factory.for_dataset("mun_flu", authority_id="deland")._endpoint
        == "https://deland.example.com/flu/0"
    )
    assert (
        factory.for_dataset("mun_flu", authority_id="ormond_beach")._endpoint
        == "https://gis.example.com/county/0"
    )


def test_non_arcgis_access_type_not_implemented() -> None:
    factory = _factory(endpoint_overrides={"official_records": ENDPOINT})
    with pytest.raises(ConnectorError) as exc:
        factory.for_dataset("official_records")
    assert exc.value.failure_class == FailureClass.SOURCE_UNAVAILABLE
    assert "not yet implemented" in exc.value.detail


def test_file_download_access_type(tmp_path) -> None:
    from connectors.filedownload import FileDownloadConnector

    factory = _factory(
        endpoint_overrides={"nwi_wetlands": "https://data.example.com/nwi.geojson"},
        cache_dir=tmp_path,
    )
    conn = factory.for_dataset("nwi_wetlands")
    assert isinstance(conn, FileDownloadConnector)


def test_connector_instances_cached() -> None:
    factory = _factory(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        endpoint_overrides={"basemap_parcels": ENDPOINT},
    )
    assert factory.for_dataset("basemap_parcels") is factory.for_dataset(
        "basemap_parcels"
    )
