"""Registry-backed EvidenceFetcher for the screening engine (M6).

``file_download`` datasets have no queryable endpoint: the artefact is
downloaded (respecting the ``download`` right), ingested from GeoJSON, and
filtered client-side against the (buffered) parcel. Other artefact formats
raise SOURCE_UNAVAILABLE until their ingest lands.
"""

from pathlib import Path

from shapely import from_wkt

from analysis import geo
from connectors.contract import (
    ConnectorError,
    DownloadRequest,
    FailureClass,
    FeaturePage,
    QueryRequest,
)
from connectors.factory import ConnectorFactory
from connectors.filedownload import FileDownloadConnector
from connectors.ingest_geojson import features_from_geojson


class RegistryEvidenceFetcher:
    def __init__(
        self,
        factory: ConnectorFactory,
        *,
        page_limit: int = 2000,
        max_pages: int = 10,
    ) -> None:
        self._factory = factory
        self._page_limit = page_limit
        self._max_pages = max_pages

    def fetch(
        self,
        dataset_id: str,
        parcel_wkt: str,
        spatial_rel: str,
        buffer_m: float | None,
        authority_id: str | None = None,
    ) -> FeaturePage:
        connector = self._factory.for_dataset(dataset_id, authority_id)

        if isinstance(connector, FileDownloadConnector):
            return self._fetch_via_download(
                connector, dataset_id, parcel_wkt, buffer_m
            )

        geometry_wkt = parcel_wkt
        rel = spatial_rel
        if buffer_m is not None:
            geometry_wkt = geo.buffer_m(from_wkt(parcel_wkt), buffer_m).wkt
            rel = "intersects"

        features = []
        offset = 0
        exceeded = False
        for _ in range(self._max_pages):
            page = connector.query(
                QueryRequest(
                    geometry_wkt=geometry_wkt,
                    spatial_rel=rel,
                    offset=offset,
                    limit=self._page_limit,
                )
            )
            features.extend(page.features)
            if page.next_offset is None:
                break
            offset = page.next_offset
        else:
            exceeded = True

        return FeaturePage(
            features=features,
            next_offset=offset if exceeded else None,
            exceeded_limit=exceeded,
        )

    def _fetch_via_download(
        self,
        connector: FileDownloadConnector,
        dataset_id: str,
        parcel_wkt: str,
        buffer_m: float | None,
    ) -> FeaturePage:
        ref = connector.download(DownloadRequest())
        content_type = (ref.content_type or "").lower()
        ext = Path(ref.path).suffix.lower()
        if "geo+json" in content_type or ext == ".geojson":
            page = features_from_geojson(
                ref.path, dataset_id, ref.retrieved_at
            )
        else:
            raise ConnectorError(
                FailureClass.SOURCE_UNAVAILABLE,
                detail=f"ingest for {ext or content_type} not implemented",
            )

        parcel = from_wkt(parcel_wkt)
        target = geo.buffer_m(parcel, buffer_m) if buffer_m is not None else parcel
        hits = [
            f
            for f in page.features
            if f.geometry_wkt and target.intersects(from_wkt(f.geometry_wkt))
        ]
        return FeaturePage(features=hits)
