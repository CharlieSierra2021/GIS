"""Connector contract — ICD §5.1/§5.2/§5.3, SRS REQ-CON.

Every provider connector implements the ``Connector`` protocol. Analysis code
consumes the contract only; provider behaviour is confined to adapters.
``download()`` is an optional capability (``Downloadable`` protocol,
file_download datasets); ``documents()`` remains deferred.
"""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel


class FieldSpec(BaseModel):
    name: str
    type: str
    nullable: bool = True


def compute_fingerprint(
    fields: list[FieldSpec], native_crs: str | None, layer_id: int | None
) -> str:
    """ICD §17 drift fingerprint: sha256 of canonical JSON of the sorted
    (name, type) field list, native CRS, and layer id."""
    canonical = {
        "fields": sorted((f.name, f.type) for f in fields),
        "native_crs": native_crs,
        "layer_id": layer_id,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True).encode("utf-8")
    ).hexdigest()


class ServiceDescriptor(BaseModel):
    provider_id: str
    dataset_id: str
    endpoint: str
    layer_id: int | None = None
    layer_name: str | None = None
    native_crs: str | None = None
    fields: list[FieldSpec] = []
    max_record_count: int | None = None
    supports_pagination: bool = False
    fingerprint: str


class Capabilities(BaseModel):
    pagination: bool
    max_features: int | None = None
    query_types: list[Literal["spatial", "attribute"]]
    crs: list[str]


class Provenance(BaseModel):
    """Three dates are recorded independently and never derived from each
    other (SRS core concept 2); absent values stay null (CON-D)."""

    dataset_id: str
    source_feature_key: str
    retrieved_at: datetime
    native_crs: str | None = None
    observation_date: str | None = None
    publication_date: str | None = None


class Feature(BaseModel):
    key: str
    attributes: dict
    geometry_wkt: str | None = None
    provenance: Provenance


class PendingInfo(BaseModel):
    """A records request in flight — the page is empty because the
    custodian has not yet fulfilled it (ICD §7 / §14 pending row)."""

    request_id: str
    status: str
    submitted_at: datetime
    expected_by: datetime | None = None
    contact: str | None = None


class FeaturePage(BaseModel):
    features: list[Feature]
    next_offset: int | None = None
    exceeded_limit: bool = False
    pending: PendingInfo | None = None


class QueryRequest(BaseModel):
    where: str = "1=1"
    geometry_wkt: str | None = None
    spatial_rel: Literal["intersects", "contains", "within"] = "intersects"
    out_fields: list[str] | None = None
    offset: int = 0
    limit: int | None = None


class FailureClass(StrEnum):
    """ICD §5.3 failure taxonomy. EMPTY_RESULT is a classification value for
    the orchestrator only — a successful zero-feature page signals it; it is
    never raised as an exception."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    SCHEMA_DRIFT = "schema_drift"
    PERMISSION_DENIED = "permission_denied"
    EMPTY_RESULT = "empty_result"


class ConnectorError(Exception):
    def __init__(self, failure_class: FailureClass, detail: str | None = None) -> None:
        super().__init__(detail or failure_class.value)
        self.failure_class = failure_class
        self.detail = detail


class HealthStatus(BaseModel):
    ok: bool
    fingerprint: str | None = None
    checked_at: datetime
    detail: str | None = None


class Connector(Protocol):
    def describe(self) -> ServiceDescriptor: ...
    def capabilities(self) -> Capabilities: ...
    def query(self, req: QueryRequest) -> FeaturePage: ...
    def health(self) -> HealthStatus: ...


class DownloadRequest(BaseModel):
    """Bulk-artefact fetch (ICD §5.2-E / §6). ``previous`` carries the
    ObjectRef from an earlier download so conditional requests
    (If-None-Match / If-Modified-Since) can short-circuit on 304."""

    url: str | None = None
    previous: "ObjectRef | None" = None


class ObjectRef(BaseModel):
    """Reference to a downloaded artefact retained in the local cache."""

    dataset_id: str
    url: str
    path: str
    sha256: str
    bytes: int
    retrieved_at: datetime
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None


class Downloadable(Protocol):
    """Optional bulk-download capability — file_download datasets only;
    spatial connectors never implement it."""

    def download(self, req: DownloadRequest) -> ObjectRef: ...
