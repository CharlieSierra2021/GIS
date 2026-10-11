"""Registry-backed connector factory.

Resolves endpoints from the registry (or overrides), instantiates the
connector for the dataset's ``access_type``, and caches one connector
instance per dataset id (``describe()`` itself is never cached — CON-A).

Only ``arcgis_query`` is implemented; ``file_download``,
``document_retrieval``, and ``records_request`` are later board items and
raise a classified failure rather than guessing.

Per-authority datasets (``per_authority: true`` in the registry, e.g.
``mun_flu``) use endpoint-override keys of the form
``<dataset_id>:<authority_id>``, falling back to the plain dataset id.
"""

import httpx

from connectors.arcgis import ArcGISFeatureServiceConnector
from connectors.contract import Connector, ConnectorError, FailureClass
from connectors.registry import Registry


class ConnectorFactory:
    def __init__(
        self,
        registry: Registry,
        *,
        client: httpx.Client | None = None,
        endpoint_overrides: dict[str, str] | None = None,
        expected_fingerprints: dict[str, str] | None = None,
    ) -> None:
        self._registry = registry
        self._client = client
        self._overrides = endpoint_overrides or {}
        self._fingerprints = expected_fingerprints or {}
        self._cache: dict[tuple[str, str | None], Connector] = {}

    def for_dataset(
        self, dataset_id: str, authority_id: str | None = None
    ) -> Connector:
        dataset = self._registry.dataset(dataset_id)

        key_id = dataset_id
        if dataset.per_authority and authority_id:
            key_id = f"{dataset_id}:{authority_id}"

        endpoint = self._overrides.get(key_id) or self._overrides.get(
            dataset_id
        ) or dataset.endpoint
        if not endpoint:
            raise ConnectorError(
                FailureClass.SOURCE_UNAVAILABLE,
                detail=f"no endpoint registered for {dataset_id}",
            )

        if dataset.access_type != "arcgis_query":
            raise ConnectorError(
                FailureClass.SOURCE_UNAVAILABLE,
                detail=f"access_type {dataset.access_type} not yet implemented",
            )

        cache_key = (dataset_id, authority_id)
        if cache_key not in self._cache:
            self._cache[cache_key] = ArcGISFeatureServiceConnector(
                dataset.provider,
                dataset,
                endpoint,
                client=self._client,
                expected_fingerprint=self._fingerprints.get(key_id)
                or self._fingerprints.get(dataset_id),
            )
        return self._cache[cache_key]
