from datetime import UTC, datetime

import pytest

from resolution.intake import IntakeKind, IntakeRequest
from workers.jobs import (
    IllegalTransition,
    InMemoryJobStore,
    Job,
    JobState,
)


def _job(state=JobState.RECEIVED) -> Job:
    now = datetime.now(UTC)
    return Job(
        id="j1",
        account_id="acct-1",
        intake=IntakeRequest(kind=IntakeKind.PARCEL_ID, parcel_id="P-001"),
        state=state,
        created_at=now,
        updated_at=now,
        registry_version="0.1.0",
        profile="florida_land_screening_v1",
        profile_version="1.0.0",
    )


def test_legal_path_records_transitions() -> None:
    job = _job()
    path = [
        JobState.RESOLVING,
        JobState.ROUTING_JURISDICTION,
        JobState.FETCHING,
        JobState.SCREENING,
        JobState.QUALITY_GATES,
        JobState.AUTO_PUBLISH,
        JobState.PUBLISHED,
    ]
    for state in path:
        job.advance(state)
    assert job.state == JobState.PUBLISHED
    assert [t.to_state for t in job.transitions] == path
    assert [t.from_state for t in job.transitions] == [JobState.RECEIVED] + path[:-1]


def test_illegal_transition_raises() -> None:
    job = _job()
    with pytest.raises(IllegalTransition):
        job.advance(JobState.PUBLISHED)


def test_store_account_isolation() -> None:
    store = InMemoryJobStore()
    store.put(_job())
    assert store.get("j1", "acct-1").id == "j1"
    with pytest.raises(KeyError):
        store.get("j1", "acct-2")
    assert store.list("acct-2") == []
