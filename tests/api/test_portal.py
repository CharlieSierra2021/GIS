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
from workers.audit import InMemoryAuditLog
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner
from workers.storage import InMemoryEvidenceStore

H = {"X-Account-Id": "acct-1"}


def _runner(registry=None) -> JobRunner:
    registry = registry or publishable_registry()
    return JobRunner(
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


@pytest.fixture()
def runner() -> JobRunner:
    return _runner()


@pytest.fixture()
def client(runner) -> TestClient:
    return TestClient(create_app(runner))


def _submit(client: TestClient, data: dict, status: int = 303) -> str | None:
    resp = client.post(
        "/portal/jobs?account=acct-1",
        data=data,
        headers=H,
        follow_redirects=False,
    )
    assert resp.status_code == status
    if status == 303:
        return resp.headers["location"].split("/portal/jobs/")[1].split("?")[0]
    return None


def test_index_requires_account(client: TestClient) -> None:
    assert client.get("/portal").status_code == 400


def test_index_lists_jobs(client: TestClient) -> None:
    _submit(client, {"kind": "parcel_id", "parcel_id": "P-001"})
    resp = client.get("/portal", headers=H)
    assert resp.status_code == 200
    assert "P-001" in resp.text
    assert "New screening request" in resp.text


def test_submit_redirects_to_job_page(client: TestClient) -> None:
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    resp = client.get(f"/portal/jobs/{job_id}", headers=H)
    assert resp.status_code == 200
    assert '<div id="map"' in resp.text
    assert "badge" in resp.text


def test_awaiting_candidate_picker_and_select(client: TestClient) -> None:
    job_id = _submit(
        client, {"kind": "address", "address": "500 Ocean Blvd"}
    )
    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "C-101" in page and "C-102" in page
    assert page.count('type="submit">Select') >= 2

    resp = client.post(
        f"/portal/jobs/{job_id}/select?account=acct-1",
        data={"parcel_id": "C-102"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "C-102" in page
    assert "Select a parcel" not in page


def test_layers_geojson_awaiting_has_candidates_no_evidence(
    client: TestClient,
) -> None:
    job_id = _submit(
        client, {"kind": "address", "address": "500 Ocean Blvd"}
    )
    data = client.get(
        f"/portal/jobs/{job_id}/layers.geojson", headers=H
    ).json()
    layers = {f["properties"]["layer"] for f in data["features"]}
    assert layers == {"candidate"}


def test_layers_geojson_display_rights(client: TestClient) -> None:
    registry = publishable_registry()
    registry.dataset("nwi_wetlands").permissions.display = None
    app = TestClient(create_app(_runner(registry)))
    job_id = _submit(app, {"kind": "address", "address": "123 Main St"})
    app.post(f"/jobs/{job_id}/publish", headers=H)

    resp = app.get(f"/portal/jobs/{job_id}/layers.geojson", headers=H)
    ds_ids = {
        f["properties"].get("dataset_id") for f in resp.json()["features"]
    }
    assert "basemap_parcels" in ds_ids  # parcel feature present
    assert "nfhl_flood" in ds_ids  # display-allowed evidence present
    assert "nwi_wetlands" not in ds_ids
    assert "nwi_wetlands" not in resp.text  # not merely hidden client-side


@pytest.mark.parametrize("display", [False, None])
def test_published_layers_recheck_current_display_rights(client, runner, display) -> None:
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    assert client.post(f"/jobs/{job_id}/publish", headers=H).status_code == 200
    manifest = runner.store.get(job_id, "acct-1").report["manifest"]
    assert "nfhl_flood" in manifest["map_layers"]
    runner.registry.dataset("nfhl_flood").permissions.display = display

    response = client.get(f"/portal/jobs/{job_id}/layers.geojson", headers=H)
    assert response.status_code == 200
    assert "nfhl_flood" not in response.text
    assert "nwi_wetlands" in response.text
    assert "nfhl_flood" in manifest["map_layers"]
    runner.registry.dataset("nfhl_flood").permissions.display = True
    response = client.get(f"/portal/jobs/{job_id}/layers.geojson", headers=H)
    assert response.status_code == 200
    assert "nfhl_flood" in response.text


@pytest.mark.parametrize("published", [False, True])
def test_layers_omit_dataset_removed_from_registry(client, runner, published) -> None:
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    if published:
        assert client.post(f"/jobs/{job_id}/publish", headers=H).status_code == 200
    runner.registry.datasets = [ds for ds in runner.registry.datasets if ds.id != "nfhl_flood"]

    response = client.get(f"/portal/jobs/{job_id}/layers.geojson", headers=H)
    assert response.status_code == 200
    assert "nfhl_flood" not in response.text
    assert "nwi_wetlands" in response.text


@pytest.mark.parametrize("report", [None, {}, {"manifest": {}}, {"manifest": {"map_layers": []}}])
def test_published_layers_require_manifest_allowlist(client, runner, report) -> None:
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    assert client.post(f"/jobs/{job_id}/publish", headers=H).status_code == 200
    job = runner.store.get(job_id, "acct-1")
    job.report = report
    runner.store.put(job)

    response = client.get(f"/portal/jobs/{job_id}/layers.geojson", headers=H)
    assert response.status_code == 200
    assert all(f["properties"]["layer"] != "evidence" for f in response.json()["features"])


def test_imagery_banner_denied_and_licensed() -> None:
    denied = TestClient(create_app(_runner()))
    job_id = _submit(denied, {"kind": "address", "address": "123 Main St"})
    page = denied.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "Aerial imagery not licensed for display." in page
    assert "<img" not in page

    registry = publishable_registry()
    registry.dataset("ortho_2024").permissions.display = True
    registry.dataset("ortho_2024").permissions.report = True
    licensed = TestClient(create_app(_runner(registry)))
    job_id = _submit(
        licensed, {"kind": "address", "address": "123 Main St"}
    )
    page = licensed.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "Aerial imagery not licensed for display." not in page


def test_invalid_form_rerenders_with_error(client: TestClient) -> None:
    resp = client.post(
        "/portal/jobs?account=acct-1", data={"kind": "address", "address": ""}
    )
    assert resp.status_code == 400
    assert "error" in resp.text
    assert "Traceback" not in resp.text


def test_demo_workspace_discloses_coverage_and_examples() -> None:
    client = TestClient(create_app(_runner(), demo_mode=True))
    page = client.get("/portal", headers=H).text
    assert "Sample data workspace" in page
    assert "Live address lookup is not connected" in page
    assert "123 Main St" in page
    assert "500 Ocean Blvd" in page


def test_unmatched_demo_address_has_recovery_not_empty_map() -> None:
    client = TestClient(create_app(_runner(), demo_mode=True))
    job_id = _submit(client, {"kind": "address", "address": "436 Pleasant Oaks Trail"})
    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "436 Pleasant Oaks Trail" in page
    assert "Address not in the sample dataset" in page
    assert "does not mean the property does not exist" in page
    assert "Edit search" in page
    assert "Try parcel ID" in page
    assert '<div id="map"' not in page
    assert "Aerial imagery not licensed for display." not in page
    retry = client.get(f"/portal?retry={job_id}", headers=H)
    assert retry.status_code == 200
    assert 'value="436 Pleasant Oaks Trail"' in retry.text
    assert client.get(f"/portal?retry={job_id}", headers={"X-Account-Id": "other"}).status_code == 404


def test_unmatched_address_outside_demo_is_not_mislabeled(client) -> None:
    job_id = _submit(client, {"kind": "address", "address": "436 Pleasant Oaks Trail"})
    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert "We could not confirm this property" in page
    assert "Address not in the sample dataset" not in page
    assert '<div id="map"' not in page


def test_invalid_form_preserves_input_and_escapes_it(client) -> None:
    response = client.post(
        "/portal/jobs", headers=H,
        data={"kind": "parcel_id", "address": '<script>alert("x")</script>'},
    )
    assert response.status_code == 400
    assert "Check your property details" in response.text
    assert "&lt;script&gt;" in response.text
    assert '<script>alert("x")</script>' not in response.text


def test_report_opens_via_portal_without_api_header(client) -> None:
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    response = client.post(
        f"/portal/jobs/{job_id}/publish?account=acct-1", follow_redirects=False,
    )
    assert response.status_code == 303
    report = client.get(f"/portal/jobs/{job_id}/report?account=acct-1")
    assert report.status_code == 200
    assert "text/html" in report.headers["content-type"]
    assert "SCREENING REPORT" in report.text
    assert client.get(f"/portal/jobs/{job_id}/report?account=other").status_code == 404
    assert client.get(f"/portal/jobs/{job_id}/manifest?account=acct-1").status_code == 200


def test_portal_report_requires_publication_and_current_report_rights(client, runner) -> None:
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    assert client.get(f"/portal/jobs/{job_id}/report", headers=H).status_code == 404
    assert client.post(
        f"/portal/jobs/{job_id}/publish", headers=H, follow_redirects=False
    ).status_code == 303
    runner.registry.dataset("nfhl_flood").permissions.report = None
    assert client.get(f"/portal/jobs/{job_id}/report", headers=H).status_code == 403
    assert client.get(f"/portal/jobs/{job_id}/manifest", headers=H).status_code == 403


def test_demo_geometry_is_not_presented_as_a_real_location() -> None:
    client = TestClient(create_app(_runner(), demo_mode=True))
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert '<div id="map" class="sample-crs"' in page
    assert "L.CRS.Simple" in page  # abstract canvas, not a geographic basemap
    assert "not a real-world location" in page
    assert "Screening findings" in page


def test_non_demo_map_uses_geographic_basemaps(client: TestClient) -> None:
    job_id = _submit(client, {"kind": "address", "address": "123 Main St"})
    page = client.get(f"/portal/jobs/{job_id}", headers=H).text
    assert '<div id="map"' in page
    assert 'id="map" class="sample-crs"' not in page
    assert "L.CRS.EPSG3857" in page
    assert "tile.openstreetmap.org" in page  # real basemap only outside demo


def test_cross_account_job_page_is_404(client: TestClient) -> None:
    job_id = _submit(client, {"kind": "parcel_id", "parcel_id": "P-001"})
    resp = client.get(
        f"/portal/jobs/{job_id}", headers={"X-Account-Id": "other"}
    )
    assert resp.status_code == 404
