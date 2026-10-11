import json
from datetime import UTC, datetime

from connectors.ingest_geojson import features_from_geojson

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def test_feature_collection_ingests(tmp_path) -> None:
    doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "w1",
                "geometry": {"type": "Point", "coordinates": [-81.0, 29.0]},
                "properties": {"WETLAND_TYPE": "Palustrine"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-81.1, 29.1]},
                "properties": {},
            },
            {
                "type": "Feature",
                "id": "w3",
                "geometry": None,
                "properties": {"WETLAND_TYPE": "Estuarine"},
            },
        ],
    }
    path = tmp_path / "wetlands.geojson"
    path.write_text(json.dumps(doc))

    page = features_from_geojson(path, "nwi_wetlands", NOW)
    assert len(page.features) == 3
    assert [f.key for f in page.features] == ["w1", "1", "w3"]
    assert page.features[0].geometry_wkt.startswith("POINT")
    assert page.features[2].geometry_wkt is None
    prov = page.features[0].provenance
    assert prov.dataset_id == "nwi_wetlands"
    assert prov.retrieved_at == NOW
    assert prov.observation_date is None
    assert prov.publication_date is None
