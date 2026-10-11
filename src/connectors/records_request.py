"""records_request connector — ICD §7 "Records request" mode.

Some datasets (official_records, clerk minutes) have no API at all: the
only access path is a public-records request to the custodian. This
connector models that workflow against a ``RecordsRequestTracker``:

- first query for a parcel opens a request and returns an EMPTY
  FeaturePage carrying ``pending`` — the engine renders a PENDING
  finding, which is neither present nor "no record";
- while SUBMITTED/ACKNOWLEDGED the same request is returned (the
  custodian's timeline, not ours — SRS REQ-PERF-03);
- FULFILLED returns one Feature per delivered DocumentRef (geometry
  None — documents have no geometry; recorded_date maps to
  observation_date, the instrument's date of record);
- DENIED / EXPIRED raise classified failures.
"""

import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from connectors.contract import (
    Capabilities,
    ConnectorError,
    FailureClass,
    Feature,
    FeaturePage,
    HealthStatus,
    PendingInfo,
    Provenance,
    QueryRequest,
    ServiceDescriptor,
)
from connectors.registry import Dataset

_WHERE_RE = re.compile(
    r"parcel_id='(?P<parcel>[^']+)'\s+AND\s+job_id='(?P<job>[^']+)'"
)


class RequestStatus(StrEnum):
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    FULFILLED = "fulfilled"
    DENIED = "denied"
    EXPIRED = "expired"


class DocumentRef(BaseModel):
    key: str
    title: str
    path: str | None = None
    sha256: str | None = None
    recorded_date: str | None = None  # instrument date of record, if stated


class RecordsRequest(BaseModel):
    id: str
    dataset_id: str
    parcel_id: str
    job_id: str
    submitted_at: datetime
    expected_by: datetime | None = None
    status: RequestStatus
    contact: str | None = None
    reference: str | None = None
    documents: list[DocumentRef] = []
    note: str | None = None


class RecordsRequestTracker(Protocol):
    def open(
        self,
        dataset_id: str,
        parcel_id: str,
        job_id: str,
        expected_days: int | None,
    ) -> RecordsRequest: ...

    def get(self, request_id: str) -> RecordsRequest: ...

    def find(self, dataset_id: str, parcel_id: str) -> RecordsRequest | None: ...

    def update(
        self,
        request_id: str,
        status: RequestStatus,
        documents: list[DocumentRef] | None = None,
        note: str | None = None,
    ) -> RecordsRequest: ...

    def list_by_job(self, job_id: str) -> list[RecordsRequest]: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InMemoryRecordsRequestTracker:
    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        self._requests: dict[str, RecordsRequest] = {}
        self._clock = clock

    def open(self, dataset_id, parcel_id, job_id, expected_days) -> RecordsRequest:
        now = self._clock()
        req = RecordsRequest(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            parcel_id=parcel_id,
            job_id=job_id,
            submitted_at=now,
            expected_by=(
                now + timedelta(days=expected_days)
                if expected_days
                else None
            ),
            status=RequestStatus.SUBMITTED,
        )
        self._requests[req.id] = req
        return req

    def get(self, request_id: str) -> RecordsRequest:
        return self._requests[request_id]

    def find(self, dataset_id: str, parcel_id: str) -> RecordsRequest | None:
        for req in self._requests.values():
            if req.dataset_id == dataset_id and req.parcel_id == parcel_id:
                return req
        return None

    def update(self, request_id, status, documents=None, note=None) -> RecordsRequest:
        req = self._requests[request_id]
        req.status = status
        if documents is not None:
            req.documents = list(documents)
        if note is not None:
            req.note = note
        return req

    def list_by_job(self, job_id: str) -> list[RecordsRequest]:
        return [r for r in self._requests.values() if r.job_id == job_id]


class RecordsRequestConnector:
    """Connector over a records-request tracker (access_type
    ``records_request``). ``query()`` is the tracking interface: the
    ``where`` clause carries ``parcel_id='…' AND job_id='…'``."""

    def __init__(
        self,
        provider_id: str,
        dataset: Dataset,
        tracker: RecordsRequestTracker,
        *,
        expected_days: int | None = 10,
        clock: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._provider_id = provider_id
        self._dataset = dataset
        self._tracker = tracker
        self._expected_days = expected_days
        self._clock = clock
        self._sleep = sleep

    def describe(self) -> ServiceDescriptor:
        import hashlib

        return ServiceDescriptor(
            provider_id=self._provider_id,
            dataset_id=self._dataset.id,
            endpoint=f"records-request:{self._dataset.id}",
            fields=[],
            fingerprint=hashlib.sha256(
                f"records-request:{self._dataset.id}".encode()
            ).hexdigest(),
        )

    def capabilities(self) -> Capabilities:
        return Capabilities(
            pagination=False, query_types=["attribute"], crs=[]
        )

    def health(self) -> HealthStatus:
        return HealthStatus(
            ok=True,
            fingerprint=self.describe().fingerprint,
            checked_at=self._clock(),
        )

    def query(self, req: QueryRequest) -> FeaturePage:
        if not self._dataset.permissions.allows("query"):
            raise ConnectorError(
                FailureClass.PERMISSION_DENIED,
                detail=f"registry denies query for {self._dataset.id}",
            )
        match = _WHERE_RE.search(req.where or "")
        if not match:
            raise ValueError(
                "records_request query requires where "
                "parcel_id='<id>' AND job_id='<id>'"
            )
        parcel_id = match.group("parcel")
        job_id = match.group("job")

        existing = self._tracker.find(self._dataset.id, parcel_id)
        if existing is None:
            req_obj = self._tracker.open(
                self._dataset.id, parcel_id, job_id, self._expected_days
            )
            return FeaturePage(features=[], pending=self._pending(req_obj))

        if existing.status in (
            RequestStatus.SUBMITTED,
            RequestStatus.ACKNOWLEDGED,
        ):
            return FeaturePage(features=[], pending=self._pending(existing))

        if existing.status == RequestStatus.DENIED:
            raise ConnectorError(
                FailureClass.PERMISSION_DENIED,
                detail=f"records request denied: {existing.note}",
            )
        if existing.status == RequestStatus.EXPIRED:
            raise ConnectorError(
                FailureClass.SOURCE_UNAVAILABLE,
                detail="records request expired",
            )

        # FULFILLED — one Feature per delivered document.
        now = self._clock()
        features = [
            Feature(
                key=doc.key,
                attributes={
                    "title": doc.title,
                    "recorded_date": doc.recorded_date,
                    "sha256": doc.sha256,
                },
                geometry_wkt=None,
                provenance=Provenance(
                    dataset_id=self._dataset.id,
                    source_feature_key=doc.key,
                    retrieved_at=now,
                    observation_date=doc.recorded_date,
                    publication_date=None,
                ),
            )
            for doc in existing.documents
        ]
        return FeaturePage(features=features)

    def _pending(self, req: RecordsRequest) -> PendingInfo:
        return PendingInfo(
            request_id=req.id,
            status=str(req.status),
            submitted_at=req.submitted_at,
            expected_by=req.expected_by,
            contact=req.contact,
        )
