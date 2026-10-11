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
    granted_registry,
    publishable_registry,
    toy_pages,
)
from workers import pipeline
from workers.jobs import IllegalTransition, InMemoryJobStore, JobState
from workers.pipeline import JobRunner

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _runner(registry, pages=None, router="toy", fetcher=None, **runner_kw) -> JobRunner:
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
        fetcher=fetcher or StubFetcher(pages if pages is not None else toy_pages()),
        registry=registry,
        profile=runner_kw.pop("profile", None) or load_profile(),
        clock=lambda: NOW,
        **runner_kw,
    )


def _states(job) -> list[JobState]:
    return [t.to_state for t in job.transitions]


class _RecordsHybrid(StubFetcher):
    """Stub pages for every dataset, except `records_dataset` which is
    served by a real RecordsRequestConnector over the shared tracker."""

    def __init__(self, pages, connector, records_dataset="official_records"):
        super().__init__(pages)
        self._conn = connector
        self._records_ds = records_dataset

    def fetch(
        self,
        dataset_id,
        parcel_wkt,
        spatial_rel,
        buffer_m,
        authority_id=None,
        job_id=None,
        parcel_id=None,
    ):
        if dataset_id == self._records_ds:
            from connectors.contract import QueryRequest

            return self._conn.query(
                QueryRequest(
                    where=f"parcel_id='{parcel_id}' AND job_id='{job_id}'"
                )
            )
        return super().fetch(
            dataset_id, parcel_wkt, spatial_rel, buffer_m, authority_id
        )


def _records_runner():
    """Runner whose `permits` area is backed by a records_request dataset
    (profile is data — a real title_documents area is a v1.1 decision)."""
    from connectors.records_request import (
        InMemoryRecordsRequestTracker,
        RecordsRequestConnector,
    )

    registry = publishable_registry()
    registry.dataset("official_records").permissions.query = True
    registry.dataset("official_records").permissions.report = True
    tracker = InMemoryRecordsRequestTracker()
    connector = RecordsRequestConnector(
        "volusia_clerk", registry.dataset("official_records"), tracker
    )
    profile = load_profile()
    profile.areas["permits"] = profile.areas["permits"].model_copy(
        update={"dataset": "official_records"}
    )
    fetcher = _RecordsHybrid(toy_pages(), connector)
    runner = _runner(
        registry,
        fetcher=fetcher,
        profile=profile,
        records_tracker=tracker,
    )
    return runner, tracker


def test_records_request_pending_then_rescreen() -> None:
    from connectors.records_request import DocumentRef, RequestStatus

    runner, tracker = _records_runner()
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.QUALIFIED_OUTPUT
    finding = next(f for f in job.screening.findings if f.area == "permits")
    assert finding.status.value == "pending"

    request = tracker.find("official_records", "P-001")
    tracker.update(
        request.id,
        RequestStatus.FULFILLED,
        documents=[DocumentRef(key="d1", title="Deed", recorded_date="2024-03-04")],
    )
    job = runner.rescreen(job.id, "acct-1")
    assert "rescreen" in (job.transitions[-6].note or "") or any(
        t.note == "rescreen" for t in job.transitions
    )
    finding = next(f for f in job.screening.findings if f.area == "permits")
    assert finding.status.value == "present"
    assert "rescreen" in [t.note for t in job.transitions]


def test_rescreen_on_published_is_illegal() -> None:
    from reports.publisher import ReportPublisher

    registry = publishable_registry()
    runner = _runner(registry, publisher=ReportPublisher(registry, clock=lambda: NOW))
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    job = runner.publish(job.id, "acct-1")
    assert job.state == JobState.PUBLISHED
    with pytest.raises(IllegalTransition):
        runner.rescreen(job.id, "acct-1")


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
    pages = toy_pages()
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
    pages = toy_pages()
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


def test_auto_publish_on_pass_publishes() -> None:
    from reports.publisher import ReportPublisher

    registry = publishable_registry()
    runner = _runner(
        registry,
        publisher=ReportPublisher(registry, clock=lambda: NOW),
        auto_publish_on_pass=True,
    )
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.PUBLISHED
    assert job.report is not None
    assert job.report["manifest"]["imagery"] == "denied"
    assert JobState.PUBLISHED in _states(job)


def test_publish_from_qualified_output() -> None:
    from reports.publisher import ReportPublisher
    from tests.support.stubs import page

    registry = publishable_registry()
    pages = toy_pages()
    pages["nwi_wetlands"] = page()  # NOT_FOUND -> QUALIFIED_OUTPUT
    runner = _runner(registry, pages=pages, publisher=ReportPublisher(registry))
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.QUALIFIED_OUTPUT
    job = runner.publish(job.id, "acct-1")
    assert job.state == JobState.PUBLISHED


def test_publish_from_human_review_is_illegal() -> None:
    from reports.publisher import ReportPublisher

    registry = publishable_registry()
    pages = toy_pages()
    pages["nfhl_flood"] = ConnectorError(
        FailureClass.SOURCE_UNAVAILABLE, detail="down"
    )
    runner = _runner(registry, pages=pages, publisher=ReportPublisher(registry))
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert job.state == JobState.HUMAN_REVIEW
    with pytest.raises(IllegalTransition):
        runner.publish(job.id, "acct-1")


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
