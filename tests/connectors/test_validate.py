import json
from pathlib import Path

import httpx
import yaml

from connectors.arcgis import ArcGISFeatureServiceConnector
from connectors.registry import load_registry
from connectors.validate import run

FIXTURES = Path(__file__).with_name("fixtures")
META = json.loads((FIXTURES / "arcgis_layer_meta.json").read_text(encoding="utf-8"))
ENDPOINT = "https://gis.example.com/arcgis/rest/services/parcels/FeatureServer/0"


def _factory(payload=None):
    def make(provider, dataset, endpoint):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload or META)

        return ArcGISFeatureServiceConnector(
            provider.id,
            dataset,
            endpoint,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    return make


def test_run_writes_fixture_and_returns_zero(tmp_path: Path) -> None:
    out = tmp_path / "fixture.yaml"
    code = run(
        [
            "--provider",
            "volusia_county_gis",
            "--dataset",
            "basemap_parcels",
            "--endpoint",
            ENDPOINT,
            "--out",
            str(out),
        ],
        connector_factory=_factory(),
    )
    assert code == 0
    record = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert record["provider"] == "volusia_county_gis"
    assert record["dataset"] == "basemap_parcels"
    assert record["native_crs"] == "EPSG:2881"
    assert record["layer_id"] == 0
    assert record["drift"] == []
    assert len(record["fingerprint"]) == 64
    assert {f["name"] for f in record["fields"]} >= {"OBJECTID", "PARID"}


def test_run_reports_drift_for_expected_field(tmp_path: Path) -> None:
    registry = load_registry()
    tampered = tmp_path / "registry.yaml"
    data = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "registry" / "volusia.yaml").read_text(
            encoding="utf-8"
        )
    )
    for ds in data["datasets"]:
        if ds["id"] == "basemap_parcels":
            ds["expected_fields"] = [{"name": "NOPE", "type": "esriFieldTypeString"}]
    tampered.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert registry.dataset("basemap_parcels") is not None  # sanity

    code = run(
        [
            "--provider",
            "volusia_county_gis",
            "--dataset",
            "basemap_parcels",
            "--endpoint",
            ENDPOINT,
            "--registry",
            str(tampered),
            "--out",
            str(tmp_path / "fixture.yaml"),
        ],
        connector_factory=_factory(),
    )
    assert code == 1
    record = yaml.safe_load((tmp_path / "fixture.yaml").read_text(encoding="utf-8"))
    assert any("NOPE" in d for d in record["drift"])


def test_run_missing_endpoint_returns_two(tmp_path: Path) -> None:
    code = run(
        [
            "--provider",
            "volusia_county_gis",
            "--dataset",
            "basemap_parcels",
            "--out",
            str(tmp_path / "fixture.yaml"),
        ],
        connector_factory=_factory(),
    )
    assert code == 2
