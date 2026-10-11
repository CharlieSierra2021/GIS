"""Registry-backed EvidenceFetcher for the screening engine (M6)."""

from shapely import from_wkt

from analysis.geo import buffer_approx
from connectors.contract import FeaturePage, QueryRequest
from connectors.factory import ConnectorFactory


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

        geometry_wkt = parcel_wkt
        rel = spatial_rel
        if buffer_m is not None:
            geometry_wkt = buffer_approx(from_wkt(parcel_wkt), buffer_m).wkt
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
