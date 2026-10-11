"""Dev seed — serves the API + portal with two pre-seeded jobs.

Builds a JobRunner on the toy parcel fixtures and stub evidence (the same
fixtures the tests use — no real endpoints), submits one published job
("123 Main St") and one job awaiting customer input ("500 Ocean Blvd",
ambiguous condo units), registers it via ``workers.runtime.set_runner``,
then starts uvicorn on port 8010.

Usage::

    .venv/Scripts/python scripts/dev_seed.py

Then browse:  http://localhost:8010/portal?account=acct-1
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shapely.geometry import box

from analysis.profile import load_profile
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from reports.publisher import ReportPublisher
from resolution.intake import IntakeKind, IntakeRequest
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import NOW, StubFetcher, publishable_registry, toy_pages
from workers import runtime
from workers.audit import InMemoryAuditLog
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner
from workers.storage import InMemoryEvidenceStore

ACCOUNT = "acct-1"


def main() -> None:
    registry = publishable_registry()
    runner = JobRunner(
        store=InMemoryJobStore(),
        resolver=ParcelResolver(build_source()),
        router=JurisdictionRouter(
            registry=registry,
            county_boundary=box(-100, -100, 100, 100),
            municipal_boundaries=[AuthorityBoundary("deland", box(0, 0, 15, 15))],
        ),
        fetcher=StubFetcher(toy_pages()),
        registry=registry,
        profile=load_profile(),
        clock=lambda: NOW,
        publisher=ReportPublisher(registry, clock=lambda: NOW),
        audit=InMemoryAuditLog(),
        evidence_store=InMemoryEvidenceStore(),
    )

    published = runner.submit(
        ACCOUNT, IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    runner.publish(published.id, ACCOUNT)
    awaiting = runner.submit(
        ACCOUNT, IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
    )
    print(f"published job:  {published.id}")
    print(f"awaiting job:   {awaiting.id}")
    print(f"portal:         http://localhost:8010/portal?account={ACCOUNT}")

    runtime.set_runner(runner)
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8010)


if __name__ == "__main__":
    main()
