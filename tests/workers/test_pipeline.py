from datetime import UTC, datetime

import pytest
from shapely.geometry import box

from analysis.profile import load_profile
from connectors.contract import ConnectorError, FailureClass
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from resolution.intake import IntakeKind, IntakeRequest
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import (
    StubFetcher,
    full_pages,
    granted_registry,
    publishable_registry,
)
from workers import pipeline
from workers.jobs import IllegalTransition, InMemoryJobStore, JobState
from workers.pipeline import JobRunner

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _runner(registry, pages=None, router="toy") -> JobRunner:
    if router == "toy":
        router_obj = JurisdictionRouter(
            registry=registry,
            county_boundary=box(-100, -100, 100, 100),
            municipal_boundaries=[AuthorityBoundary("deland", box(0, 0, 15, 15))],
        )
    else:
        router_obj = None
    return JobRunner(
        store=InMemoryJobStore(),
        resolver=ParcelResolver(build_source()),
        router=router_obj,
        fetcher=StubFetcher(pages if pages is not None else full_pages()),
        registry=registry,
        profile=load_profile(),
        clock=lambda: NOW,
    )


def _states(job) -> list[JobState]:
    return [t.to_state for t in job.transitions]


def test_address_happy_path_auto_publishes() -> None:
    runner = _runner(publishable_registry())
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.AUTO_PUBLISH
    assert JobState.FETCHING in _states(job)
    assert JobState.SCREENING in _states(job)
    assert job.routing["authority_id"] == "deland"
    assert job.screening is not None and len(job.screening.findings) == 9


def test_awaiting_then_customer_select_resumes() -> None:
    runner = _runner(publishable_registry())
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
    )
    assert job.state == JobState.AWAITING_CUSTOMER_INPUT
    assert len(job.resolution.candidates) == 3

    job = runner.select_candidate(job.id, "acct-1", "C-101")
    assert job.resolution.customer_selection == "C-101"
    assert job.state in (JobState.AUTO_PUBLISH, JobState.QUALIFIED_OUTPUT)


def test_select_candidate_on_non_awaiting_raises() -> None:
    runner = _runner(publishable_registry())
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    with pytest.raises(IllegalTransition):
        runner.select_candidate(job.id, "acct-1", "C-101")


def test_unresolvable_intake_fails() -> None:
    runner = _runner(publishable_registry())
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.PARCEL_ID, parcel_id="ZZZ")
    )
    assert job.state == JobState.FAILED
    assert job.error


def test_no_router_degrades_jurisdiction() -> None:
    runner = _runner(publishable_registry(), router=None)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.routing["status"] == "unresolved"
    land_use = next(f for f in job.screening.findings if f.area == "land_use")
    assert land_use.status.value == "not_assessed"


def test_fetch_failure_mandatory_goes_to_review() -> None:
    pages = full_pages()
    pages["nfhl_flood"] = ConnectorError(
        FailureClass.SOURCE_UNAVAILABLE, detail="down"
    )
    runner = _runner(publishable_registry(), pages=pages)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.HUMAN_REVIEW


def test_null_report_right_blocks() -> None:
    # query granted but report left null -> license gate blocks.
    runner = _runner(granted_registry())
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.BLOCKED


def test_review_publish_path() -> None:
    pages = full_pages()
    pages["nfhl_flood"] = ConnectorError(
        FailureClass.SOURCE_UNAVAILABLE, detail="down"
    )
    runner = _runner(publishable_registry(), pages=pages)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.HUMAN_REVIEW
    job = runner.review(job.id, "acct-1", "rev-1", "publish", "looks fine")
    assert job.state == JobState.AUTO_PUBLISH
    assert job.gates.review["reviewer"] == "rev-1"


def test_screen_exception_fails_job_not_raises(monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(pipeline, "screen", boom)
    runner = _runner(publishable_registry())
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.FAILED
    assert "engine exploded" in job.error
