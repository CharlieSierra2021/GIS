from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from connectors.contract import ConnectorError, FailureClass, QueryRequest
from connectors.records_request import (
    DocumentRef,
    InMemoryRecordsRequestTracker,
    RecordsRequestConnector,
    RequestStatus,
)
from connectors.registry import load_registry
from workers.storage import SqlRecordsRequestTracker, create_schema

NOW = datetime(2025, 6, 1, tzinfo=UTC)
WHERE = "parcel_id='P-001' AND job_id='job-1'"


def _dataset(query=True):
    reg = load_registry().model_copy(deep=True)
    ds = reg.dataset("official_records")
    ds.permissions.query = query
    return ds


def _conn(tracker=None, **kw):
    return RecordsRequestConnector(
        "volusia_clerk", _dataset(), tracker or InMemoryRecordsRequestTracker(),
        clock=lambda: NOW, sleep=lambda s: None, **kw,
    )


def test_first_query_opens_request_pending() -> None:
    tracker = InMemoryRecordsRequestTracker(clock=lambda: NOW)
    page = _conn(tracker).query(QueryRequest(where=WHERE))
    assert page.features == []
    assert page.pending is not None
    assert page.pending.status == "submitted"
    assert page.pending.expected_by is not None


def test_second_query_reuses_request() -> None:
    tracker = InMemoryRecordsRequestTracker(clock=lambda: NOW)
    conn = _conn(tracker)
    first = conn.query(QueryRequest(where=WHERE)).pending
    second = conn.query(QueryRequest(where=WHERE)).pending
    assert first.request_id == second.request_id


def test_fulfilled_returns_documents() -> None:
    tracker = InMemoryRecordsRequestTracker(clock=lambda: NOW)
    conn = _conn(tracker)
    req_id = conn.query(QueryRequest(where=WHERE)).pending.request_id
    tracker.update(
        req_id,
        RequestStatus.FULFILLED,
        documents=[
            DocumentRef(key="d1", title="Deed 2024-01", recorded_date="2024-03-04"),
            DocumentRef(key="d2", title="Mortgage", recorded_date=None),
        ],
    )
    page = conn.query(QueryRequest(where=WHERE))
    assert page.pending is None
    assert len(page.features) == 2
    assert page.features[0].provenance.observation_date == "2024-03-04"
    assert page.features[1].provenance.observation_date is None
    assert page.features[0].attributes["title"] == "Deed 2024-01"


def test_denied_and_expired_map_failures() -> None:
    tracker = InMemoryRecordsRequestTracker(clock=lambda: NOW)
    conn = _conn(tracker)
    req_id = conn.query(QueryRequest(where=WHERE)).pending.request_id
    tracker.update(req_id, RequestStatus.DENIED, note="fee unpaid")
    with pytest.raises(ConnectorError) as exc:
        conn.query(QueryRequest(where=WHERE))
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED
    assert "fee unpaid" in exc.value.detail

    tracker2 = InMemoryRecordsRequestTracker(clock=lambda: NOW)
    conn2 = _conn(tracker2)
    req_id = conn2.query(QueryRequest(where=WHERE)).pending.request_id
    tracker2.update(req_id, RequestStatus.EXPIRED)
    with pytest.raises(ConnectorError) as exc:
        conn2.query(QueryRequest(where=WHERE))
    assert exc.value.failure_class == FailureClass.SOURCE_UNAVAILABLE


def test_query_right_none_denied_before_tracker() -> None:
    tracker = InMemoryRecordsRequestTracker(clock=lambda: NOW)
    ds = _dataset(query=None)
    conn = RecordsRequestConnector(
        "volusia_clerk", ds, tracker, clock=lambda: NOW
    )
    with pytest.raises(ConnectorError) as exc:
        conn.query(QueryRequest(where=WHERE))
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED
    assert tracker.find("official_records", "P-001") is None


def test_where_without_parcel_id_raises() -> None:
    with pytest.raises(ValueError, match="parcel_id"):
        _conn().query(QueryRequest(where="1=1"))


def test_sql_tracker_roundtrip() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    tracker = SqlRecordsRequestTracker(engine, clock=lambda: NOW)

    req = tracker.open("official_records", "P-001", "job-1", 10)
    assert req.status == RequestStatus.SUBMITTED
    assert tracker.get(req.id).parcel_id == "P-001"
    assert tracker.find("official_records", "P-001").id == req.id
    assert tracker.find("official_records", "P-999") is None

    tracker.update(
        req.id,
        RequestStatus.FULFILLED,
        documents=[DocumentRef(key="d1", title="Deed")],
        note="delivered",
    )
    got = tracker.get(req.id)
    assert got.status == RequestStatus.FULFILLED
    assert got.documents[0].title == "Deed"
    assert [r.id for r in tracker.list_by_job("job-1")] == [req.id]
