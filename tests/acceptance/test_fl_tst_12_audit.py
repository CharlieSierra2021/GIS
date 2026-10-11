import hashlib

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


@pytest.mark.acceptance
def test_fl_tst_12_evidence_set_reconstructs(engine) -> None:
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
    assert es.complete
    assert es.registry_version == job.report["manifest"]["registry_version"]

    rows = {r.dataset_id: r for r in runner.evidence_store.list(job.id)}
    for rf in es.findings:
        if rf.finding.citation is None:
            continue
        ds_id = rf.finding.citation.dataset_id
        stored = rows[ds_id]
        # Artifact sha256 matches the digest of the stored page JSON.
        assert rf.artifacts
        assert stored.sha256 == hashlib.sha256(
            __import__("json").dumps(stored.page, sort_keys=True, default=str)
            .encode()
        ).hexdigest()


@pytest.mark.acceptance
def test_fl_tst_12_cache_denied_is_a_gap_not_an_omission(engine) -> None:
    registry = publishable_registry()
    for ds in registry.datasets:
        ds.permissions.cache = True
    registry.dataset("nwi_wetlands").permissions.cache = None
    runner = _runner(engine, registry)
    job = runner.submit(
        "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    job = runner.publish(job.id, "acct-1")

    es = reconstruct_evidence_set(
        job.id, "acct-1", runner.audit, runner.evidence_store
    )
    assert not es.complete
    assert "nwi_wetlands" in es.gaps
    assert any(f.finding.citation.dataset_id == "nwi_wetlands" for f in es.findings if f.finding.citation)
