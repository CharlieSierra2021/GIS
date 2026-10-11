"""GeoJSON ingest for file_download datasets.

Converts a downloaded GeoJSON FeatureCollection into our ``Feature`` model
so the screening pipeline can consume it client-side. Shapefile/GDB ingest
is a later item — it needs GDAL/Fiona, which are deploy-time dependencies.
"""

import json
from datetime import datetime
from pathlib import Path

from shapely.geometry import shape

from connectors.contract import Feature, FeaturePage, Provenance


def features_from_geojson(
    path: str | Path,
    dataset_id: str,
    retrieved_at: datetime,
    native_crs: str = "EPSG:4326",
) -> FeaturePage:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
    features = []
    for i, f in enumerate(doc.get("features", [])):
        geom = f.get("geometry")
        key = str(f.get("id", i))
        features.append(
            Feature(
                key=key,
                attributes=dict(f.get("properties") or {}),
                geometry_wkt=shape(geom).wkt if geom else None,
                provenance=Provenance(
                    dataset_id=dataset_id,
                    source_feature_key=key,
                    retrieved_at=retrieved_at,
                    native_crs=native_crs,
                ),
            )
        )
    return FeaturePage(features=features)
