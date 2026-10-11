import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from analysis.profile import load_profile
from api.main import create_app
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import (
    NOW,
    StubFetcher,
    full_pages,
    publishable_registry,
)
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner

H = {"X-Account-Id": "acct-1"}


@pytest.fixture()
def client() -> TestClient:
    registry = publishable_registry()
    router = JurisdictionRouter(
        registry=registry,
        county_boundary=box(-100, -100, 100, 100),
        municipal_boundaries=[AuthorityBoundary("deland", box(0, 0, 15, 15))],
    )
    runner = JobRunner(
        store=InMemoryJobStore(),
        resolver=ParcelResolver(build_source()),
        router=router,
        fetcher=StubFetcher(full_pages()),
        registry=registry,
        profile=load_profile(),
        clock=lambda: NOW,
    )
    return TestClient(create_app(runner))


@pytest.mark.acceptance
def test_fl_tst_01_portfolio_rows_isolated(client: TestClient) -> None:
    csv_text = (
        "kind,address,unit,parcel_id,geometry_wkt\n"
        "parcel_id,,,P-001,\n"
        "bogus,,,,\n"
        "parcel_id,,,P-002,\n"
    )
    resp = client.post(
        "/portfolios",
        files={"file": ("p.csv", csv_text, "text/csv")},
        headers=H,
    )
    assert resp.status_code == 201
    results = resp.json()["results"]
    assert "job_id" in results[0]
    assert "error" in results[1]
    assert "job_id" in results[2]


@pytest.mark.acceptance
def test_fl_tst_03_ambiguous_resume_via_api(client: TestClient) -> None:
    resp = client.post(
        "/jobs", json={"kind": "address", "address": "500 Ocean Blvd"}, headers=H
    )
    body = resp.json()
    assert body["state"] == "awaiting_customer_input"
    assert body["resolution"]["parcel_id"] is None  # nothing auto-picked

    sel = client.post(
        f"/jobs/{body['id']}/select-candidate",
        json={"parcel_id": "C-101"},
        headers=H,
    )
    assert sel.status_code == 200
    assert sel.json()["resolution"]["customer_selection"] == "C-101"
    assert sel.json()["state"] in ("auto_publish", "qualified_output")
