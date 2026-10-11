import hashlib
from datetime import UTC, datetime

import pytest
from shapely.geometry import box

from analysis.profile import load_profile
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from reports.publisher import ReportPublisher
from resolution.intake import IntakeKind, IntakeRequest
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import (
    StubFetcher,
    full_pages,
    publishable_registry,
)
from workers.jobs import InMemoryJobStore, JobState
from workers.pipeline import JobRunner

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _runner(registry=None, **kw):
    registry = registry or publishable_registry()
    router = JurisdictionRouter(
        registry=registry,
        county_boundary=box(-100, -100, 100, 100),
        municipal_boundaries=[AuthorityBoundary("deland", box(0, 0, 15, 15))],
    )
    return JobRunner(
        store=InMemoryJobStore(),
        resolver=ParcelResolver(build_source()),
        router=router,
        fetcher=StubFetcher(full_pages()),
        registry=registry,
        profile=load_profile(),
        clock=lambda: NOW,
        **kw,
    )


def _job(runner=None, registry=None):
    runner = runner or _runner(registry)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    return runner, job


def test_publish_renders_full_report() -> None:
    registry = publishable_registry()
    _runner, job = _job(registry=registry)
    publisher = ReportPublisher(registry, clock=lambda: NOW)
    out = publisher.publish(job)
    html = out.html

    for f in job.screening.findings:
        if f.status.value == "present":
            assert f.statement in html
    assert "unknown" in html  # None observation/publication dates
    assert "not a survey" in html
    assert "ortho_2024" in html  # licence disclosure row always present
    assert "registry 0.1.0" in html

    m = out.manifest
    assert m.imagery == "denied"
    assert "Aerial imagery not licensed for display." in html
    assert "<img" not in html
    assert m.html_sha256 == hashlib.sha256(html.encode("utf-8")).hexdigest()
    assert m.pdf["note"] == "pdf renderer not configured"


def test_licensed_imagery_shows_placeholder() -> None:
    registry = publishable_registry()
    ortho = registry.dataset("ortho_2024").permissions
    ortho.display = True
    ortho.report = True
    _, job = _job(registry=registry)
    out = ReportPublisher(registry, clock=lambda: NOW).publish(job)
    assert out.manifest.imagery == "licensed"
    assert "<img" in out.html


def test_publish_refuses_blocked_and_review() -> None:
    registry = publishable_registry()
    _runner, job = _job(registry=registry)
    publisher = ReportPublisher(registry)
    job.state = JobState.BLOCKED
    job.gates.disposition = job.gates.disposition.BLOCKED
    with pytest.raises(ValueError):
        publisher.publish(job)

    _runner2, job2 = _job()
    job2.state = JobState.HUMAN_REVIEW
    from quality.gates import Disposition

    job2.gates.disposition = Disposition.HUMAN_REVIEW
    with pytest.raises(ValueError):
        ReportPublisher(publishable_registry()).publish(job2)


def test_autoescape_escapes_evidence_html() -> None:
    registry = publishable_registry()
    _, job = _job(registry=registry)
    flood = next(f for f in job.screening.findings if f.area == "flood")
    flood.evidence["zones"] = ["<script>alert(1)</script>"]
    out = ReportPublisher(registry, clock=lambda: NOW).publish(job)
    assert "&lt;script&gt;" in out.html
    assert "<script>alert(1)</script>" not in out.html
