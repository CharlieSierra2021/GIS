"""FL-TST-14 portal half + FL-TST-03 portal flow (acceptance)."""

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from analysis.profile import load_profile
from api.main import create_app
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from reports.publisher import ReportPublisher
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import NOW, StubFetcher, publishable_registry, toy_pages
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner

H = {"X-Account-Id": "acct-1"}


def _app(registry=None) -> TestClient:
    registry = registry or publishable_registry()
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
    )
    return TestClient(create_app(runner))


@pytest.mark.acceptance
def test_fl_tst_14_portal_imagery_denied_no_display_denied_geometry() -> None:
    registry = publishable_registry()
    registry.dataset("nwi_wetlands").permissions.display = None
    client = _app(registry)

    resp = client.post(
        "/portal/jobs?account=acct-1",
        data={"kind": "address", "address": "123 Main St"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].split("/portal/jobs/")[1].split("?")[0]
    client.post(f"/jobs/{job_id}/publish", headers=H)

    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "Aerial imagery not licensed for display." in page
    assert "<img" not in page

    layers = client.get(
        f"/portal/jobs/{job_id}/layers.geojson", headers=H
    )
    assert layers.status_code == 200
    assert "nwi_wetlands" not in layers.text
    ds_ids = {
        f["properties"].get("dataset_id")
        for f in layers.json()["features"]
    }
    assert "nfhl_flood" in ds_ids  # display-allowed evidence still drawn


@pytest.mark.acceptance
def test_fl_tst_03_portal_ambiguous_select_flow() -> None:
    """Ambiguous condo address -> picker -> customer select -> resumes,
    via portal forms only (no JSON API)."""
    client = _app()
    resp = client.post(
        "/portal/jobs?account=acct-1",
        data={"kind": "address", "address": "500 Ocean Blvd"},
        follow_redirects=False,
    )
    job_id = resp.headers["location"].split("/portal/jobs/")[1].split("?")[0]

    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "Select a parcel" in page  # no auto-pick

    client.post(
        f"/portal/jobs/{job_id}/select?account=acct-1",
        data={"parcel_id": "C-101"},
    )
    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "Select a parcel" not in page

    job = client.get(f"/jobs/{job_id}", headers=H).json()
    assert job["resolution"]["customer_selection"] == "C-101"
    assert job["state"] in ("auto_publish", "qualified_output")
