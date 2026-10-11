import pytest
from shapely.geometry import box
from sqlalchemy import create_engine

from analysis.profile import load_profile
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from reports.publisher import ReportPublisher
from resolution.intake import IntakeKind, IntakeRequest
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import NOW, StubFetcher, publishable_registry, toy_pages
from workers.audit import AuditEventType
from workers.jobs import JobState
from workers.pipeline import JobRunner
from workers.storage import (
    SqlAuditLog,
    SqlEvidenceStore,
    SqlJobStore,
    create_schema,
)


@pytest.fixture()
def sql(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path}/test.db")
    create_schema(engine)
    return engine


def _runner(engine, registry=None):
    registry = registry or publishable_registry()
    router = JurisdictionRouter(
        registry=registry,
        county_boundary=box(-100, -100, 100, 100),
        municipal_boundaries=[AuthorityBoundary("deland", box(0, 0, 15, 15))],
    )
    return JobRunner(
        store=SqlJobStore(engine),
        resolver=ParcelResolver(build_source()),
        router=router,
        fetcher=StubFetcher(toy_pages()),
        registry=registry,
        profile=load_profile(),
        clock=lambda: NOW,
        publisher=ReportPublisher(registry, clock=lambda: NOW),
        audit=SqlAuditLog(engine),
        evidence_store=SqlEvidenceStore(engine),
    )


def test_full_pipeline_audit_trail(sql) -> None:
    runner = _runner(sql)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    job = runner.publish(job.id, "acct-1")
    assert job.state == JobState.PUBLISHED

    events = SqlAuditLog(sql).events(job.id, "acct-1")
    types = [e.type for e in events]
    assert types[0] == AuditEventType.JOB_CREATED
    for t in (
        AuditEventType.RESOLUTION,
        AuditEventType.ROUTING,
        AuditEventType.SCREENING,
        AuditEventType.GATE_DECISION,
        AuditEventType.PUBLISHED,
    ):
        assert t in types
    assert types.count(AuditEventType.GATE_RESULT) == 5
    assert types.count(AuditEventType.TRANSITION) == len(job.transitions)


def test_evidence_rows_captured_per_fetch(sql) -> None:
    # permits gets query=True but cache stays None -> stub row, not retained.
    registry = publishable_registry()
    registry.dataset("permits").permissions.cache = None
    runner = _runner(sql, registry)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )

    rows = {r.dataset_id: r for r in SqlEvidenceStore(sql).list(job.id)}
    # Every dataset the fetcher served produced a row.
    for ds_id in ("nfhl_flood", "mun_flu", "permits"):
        assert ds_id in rows
    assert rows["nfhl_flood"].sha256
    assert rows["mun_flu"].authority_id == "deland"
    assert rows["permits"].page is None
    assert "cache right denied" in rows["permits"].note
