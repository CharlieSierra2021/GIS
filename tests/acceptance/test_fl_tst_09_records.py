"""FL-TST-09 (pending-path half) — records request lifecycle end-to-end
through the API: pending finding renders with its disclosure; after ops
fulfilment + rescreen the report shows the documents with recorded dates.
"""

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from analysis.profile import load_profile
from api.main import create_app
from connectors.contract import QueryRequest
from connectors.records_request import (
    InMemoryRecordsRequestTracker,
    RecordsRequestConnector,
)
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from reports.publisher import ReportPublisher
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import NOW, StubFetcher, publishable_registry, toy_pages
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner

H = {"X-Account-Id": "acct-1"}


class _RecordsHybrid(StubFetcher):
    def __init__(self, pages, connector):
        super().__init__(pages)
        self._conn = connector

    def fetch(
        self, dataset_id, *args, job_id=None, parcel_id=None, **kwargs
    ):
        if dataset_id == "official_records":
            return self._conn.query(
                QueryRequest(
                    where=f"parcel_id='{parcel_id}' AND job_id='{job_id}'"
                )
            )
        return super().fetch(dataset_id, *args, **kwargs)


def _app():
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
    runner = JobRunner(
        store=InMemoryJobStore(),
        resolver=ParcelResolver(build_source()),
        router=JurisdictionRouter(
            registry=registry,
            county_boundary=box(-100, -100, 100, 100),
            municipal_boundaries=[AuthorityBoundary("deland", box(0, 0, 15, 15))],
        ),
        fetcher=_RecordsHybrid(toy_pages(), connector),
        registry=registry,
        profile=profile,
        clock=lambda: NOW,
        publisher=ReportPublisher(registry, clock=lambda: NOW),
        records_tracker=tracker,
    )
    return TestClient(create_app(runner))


def _new_job(client, address="123 Main St") -> dict:
    resp = client.post(
        "/jobs", json={"kind": "address", "address": address}, headers=H
    )
    job = resp.json()
    assert job["state"] == "qualified_output"
    permits = next(
        f for f in job["screening"]["findings"] if f["area"] == "permits"
    )
    assert permits["status"] == "pending"
    return job


@pytest.mark.acceptance
def test_fl_tst_09_pending_then_fulfilled_rescreen() -> None:
    client = _app()

    # --- Job A: pending path renders in the published report.
    job_a = _new_job(client)
    client.post(f"/jobs/{job_a['id']}/publish", headers=H)
    report = client.get(f"/jobs/{job_a['id']}/report", headers=H).text
    assert "pending" in report
    assert "REQ-PERF-03" in report  # pending disclosure rendered

    # --- Job B: fulfil the request, rescreen, republish.
    # A different parcel — requests dedupe per (dataset, parcel).
    job_b = _new_job(client, address="456 Oak Ave")
    requests = client.get(
        "/records-requests", params={"job_id": job_b["id"]}, headers=H
    ).json()
    assert len(requests) == 1
    req_id = requests[0]["id"]

    upd = client.post(
        f"/records-requests/{req_id}",
        json={
            "status": "fulfilled",
            "documents": [
                {
                    "key": "d1",
                    "title": "Warranty Deed 2024-1188",
                    "recorded_date": "2024-03-04",
                    "sha256": "ab12",
                }
            ],
        },
        headers=H,
    )
    assert upd.status_code == 200

    rescreen = client.post(f"/jobs/{job_b['id']}/rescreen", headers=H)
    assert rescreen.status_code == 200
    job2 = rescreen.json()
    permits2 = next(
        f for f in job2["screening"]["findings"] if f["area"] == "permits"
    )
    assert permits2["status"] == "present"
    assert any(t["note"] == "rescreen" for t in job2["transitions"])

    client.post(f"/jobs/{job_b['id']}/publish", headers=H)
    report2 = client.get(f"/jobs/{job_b['id']}/report", headers=H).text
    assert "2024-03-04" in report2  # recorded instrument date shown
    assert 'class="status-pending"' not in report2

    # A published job cannot be rescreened.
    again = client.post(f"/jobs/{job_b['id']}/rescreen", headers=H)
    assert again.status_code == 409
