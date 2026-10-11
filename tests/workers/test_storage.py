from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from resolution.intake import IntakeKind, IntakeRequest
from tests.support.stubs import feat, page
from workers.audit import AuditEvent, AuditEventType
from workers.jobs import Job, JobState
from workers.storage import (
    SqlAuditLog,
    SqlEvidenceStore,
    SqlJobStore,
    create_schema,
)

NOW = datetime(2025, 6, 1, tzinfo=UTC)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite+pysqlite:///:memory:")
    create_schema(eng)
    return eng


def _job() -> Job:
    return Job(
        id="j1",
        account_id="acct-1",
        intake=IntakeRequest(kind=IntakeKind.PARCEL_ID, parcel_id="P-001"),
        created_at=NOW,
        updated_at=NOW,
        registry_version="0.1.0",
        profile="florida_land_screening_v1",
        profile_version="1.0.0",
    )


def test_job_store_roundtrip_and_isolation(engine) -> None:
    store = SqlJobStore(engine)
    job = _job()
    store.put(job)
    loaded = store.get("j1", "acct-1")
    assert loaded == job
    with pytest.raises(KeyError):
        store.get("j1", "acct-2")
    assert [j.id for j in store.list("acct-1")] == ["j1"]

    job.state = JobState.PUBLISHED
    store.put(job)
    assert store.get("j1", "acct-1").state == JobState.PUBLISHED


def test_audit_log_ordering(engine) -> None:
    log = SqlAuditLog(engine)
    for i, t in enumerate([AuditEventType.JOB_CREATED, AuditEventType.TRANSITION]):
        ev = log.append(
            AuditEvent(
                job_id="j1",
                account_id="acct-1",
                at=NOW,
                type=t,
                payload={"i": i},
                registry_version="0.1.0",
            )
        )
        assert ev.id is not None
    events = log.events("j1", "acct-1")
    assert [e.type for e in events] == [
        AuditEventType.JOB_CREATED,
        AuditEventType.TRANSITION,
    ]
    assert log.events("j1", "other") == []


def test_evidence_store_cache_right(engine) -> None:
    store = SqlEvidenceStore(engine)
    p = page(feat("k1", {"A": 1}))
    store.put("j1", "ds1", None, p, allowed=True, retrieved_at=NOW)
    store.put("j1", "ds2", None, p, allowed=False)

    rows = store.list("j1")
    assert rows[0].sha256 and len(rows[0].sha256) == 64
    assert rows[0].page["features"][0]["key"] == "k1"
    assert rows[1].page is None
    assert rows[1].sha256 is None
    assert "cache right denied" in rows[1].note
