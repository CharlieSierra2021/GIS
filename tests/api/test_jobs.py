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


def test_create_job_requires_account_header(client: TestClient) -> None:
    resp = client.post("/jobs", json={"kind": "parcel_id", "parcel_id": "P-001"})
    assert resp.status_code == 400


def test_create_and_get_job(client: TestClient) -> None:
    resp = client.post(
        "/jobs", json={"kind": "parcel_id", "parcel_id": "P-001"}, headers=H
    )
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    other = client.get(f"/jobs/{job_id}", headers={"X-Account-Id": "acct-2"})
    assert other.status_code == 404
    assert client.get(f"/jobs/{job_id}", headers=H).status_code == 200


def test_awaiting_candidates_then_select(client: TestClient) -> None:
    resp = client.post(
        "/jobs", json={"kind": "address", "address": "500 Ocean Blvd"}, headers=H
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["state"] == "awaiting_customer_input"
    assert set(body["candidates"]) == {"C-000", "C-101", "C-102"}

    sel = client.post(
        f"/jobs/{body['id']}/select-candidate",
        json={"parcel_id": "C-102"},
        headers=H,
    )
    assert sel.status_code == 200
    assert sel.json()["resolution"]["customer_selection"] == "C-102"
    assert sel.json()["state"] != "awaiting_customer_input"


def test_review_on_non_review_state_409(client: TestClient) -> None:
    resp = client.post(
        "/jobs", json={"kind": "parcel_id", "parcel_id": "P-001"}, headers=H
    )
    job_id = resp.json()["id"]
    review = client.post(
        f"/jobs/{job_id}/review",
        json={"reviewer": "r", "approve": "publish", "rationale": "x"},
        headers=H,
    )
    assert review.status_code == 409


def test_portfolio_row_isolation(client: TestClient) -> None:
    csv_text = (
        "kind,address,unit,parcel_id,geometry_wkt\n"
        "parcel_id,,,P-001,\n"
        "bogus,,,,\n"
        "address,123 Main St,,,\n"
    )
    resp = client.post(
        "/portfolios",
        files={"file": ("p.csv", csv_text, "text/csv")},
        headers=H,
    )
    assert resp.status_code == 201
    results = resp.json()["results"]
    assert len(results) == 3
    assert results[0].get("job_id")
    assert "error" in results[1]
    assert results[2].get("job_id")
