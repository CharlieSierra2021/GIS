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
from workers.pipeline import JobRunner
from workers.reconstruct import reconstruct_evidence_set
from workers.storage import (
    SqlAuditLog,
    SqlEvidenceStore,
    SqlJobStore,
    create_schema,
)


def _runner(engine, registry):
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


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite+pysqlite:///{tmp_path}/test.db")
    create_schema(eng)
    return eng


def test_reconstruction_complete(engine) -> None:
    registry = publishable_registry()
    for ds in registry.datasets:
        ds.permissions.cache = True
    runner = _runner(engine, registry)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    job = runner.publish(job.id, "acct-1")

    es = reconstruct_evidence_set(
        job.id, "acct-1", runner.audit, runner.evidence_store
    )
    assert es.complete is True
    assert es.gaps == []
    assert len(es.findings) == len(job.screening.findings)
    assert es.manifest is not None
    assert es.registry_version == job.registry_version
    assert es.resolution["parcel_id"] == "P-001"


def test_cache_denied_dataset_reported_as_gap(engine) -> None:
    registry = publishable_registry()
    for ds in registry.datasets:
        ds.permissions.cache = True
    registry.dataset("nfhl_flood").permissions.cache = None
    runner = _runner(engine, registry)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    job = runner.publish(job.id, "acct-1")

    es = reconstruct_evidence_set(
        job.id, "acct-1", runner.audit, runner.evidence_store
    )
    assert es.complete is False
    assert es.gaps == ["nfhl_flood"]
    # The finding itself is still listed — the gap is honest, not hidden.
    flood = next(f for f in es.findings if f.finding.area == "flood")
    assert flood.artifacts[0].sha256 is None
    assert "cache right denied" in flood.artifacts[0].note
