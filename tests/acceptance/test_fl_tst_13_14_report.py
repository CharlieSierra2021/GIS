import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from analysis.findings import check_boundary_language
from analysis.profile import load_profile
from api.main import create_app
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from reports.publisher import ReportPublisher
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import NOW, StubFetcher, full_pages, publishable_registry
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner

H = {"X-Account-Id": "acct-1"}


def _runner(registry=None):
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
        publisher=ReportPublisher(registry, clock=lambda: NOW),
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(_runner()))


def _published_job(client: TestClient) -> dict:
    resp = client.post(
        "/jobs", json={"kind": "parcel_id", "parcel_id": "P-001"}, headers=H
    )
    job_id = resp.json()["id"]
    pub = client.post(f"/jobs/{job_id}/publish", headers=H)
    assert pub.status_code == 200
    return pub.json()


@pytest.mark.acceptance
def test_fl_tst_13_findings_cited_and_boundary_clean(client: TestClient) -> None:
    job = _published_job(client)
    manifest = client.get(f"/jobs/{job['id']}/manifest", headers=H).json()
    disclosure_ids = {d["dataset_id"] for d in manifest["disclosures"]}

    store_job = client.get(f"/jobs/{job['id']}", headers=H).json()
    for f in store_job["screening"]["findings"]:
        # Every finding statement passes the ICD §10 boundary check.
        assert check_boundary_language(f["statement"]) == []
        if f["citation"]:
            assert f["citation"]["dataset_id"] in disclosure_ids


@pytest.mark.acceptance
def test_fl_tst_14_imagery_denied_end_to_end(client: TestClient) -> None:
    job = _published_job(client)
    html = client.get(f"/jobs/{job['id']}/report", headers=H).text
    manifest = client.get(f"/jobs/{job['id']}/manifest", headers=H).json()

    assert "Aerial imagery not licensed for display." in html
    assert "<img" not in html
    ortho = next(
        d for d in manifest["disclosures"] if d["dataset_id"] == "ortho_2024"
    )
    assert ortho["display_allowed"] is False
    assert manifest["imagery"] == "denied"


@pytest.mark.acceptance
def test_fl_tst_14_imagery_licensed_when_registry_grants() -> None:
    registry = publishable_registry()
    ortho = registry.dataset("ortho_2024").permissions
    ortho.display = True
    ortho.report = True
    client = TestClient(create_app(_runner(registry)))
    job = _published_job(client)
    manifest = client.get(f"/jobs/{job['id']}/manifest", headers=H).json()
    html = client.get(f"/jobs/{job['id']}/report", headers=H).text
    assert manifest["imagery"] == "licensed"
    assert "<img" in html
