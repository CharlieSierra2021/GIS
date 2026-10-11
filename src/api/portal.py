"""Customer portal — SRS REQ-PTL-01..03, REQ-RES-03.

Server-rendered pages (Jinja2 + vanilla JS + Leaflet 1.9.4 from a pinned
CDN URL with SRI; no build tooling). Account identity arrives as the
``X-Account-Id`` header OR the ``?account=`` query parameter so a browser
can navigate forms — real auth replaces this shim later; store-level
account isolation (REQ-SEC-03) still applies underneath.

REQ-PTL-03 lives in ``layers_geojson``: evidence geometry is emitted ONLY
for datasets whose ``display`` right is allowed (post-publication: only
the manifest's ``map_layers``). Denied geometry is absent from the
response entirely — never shipped to the client and hidden there.
"""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from shapely.geometry import mapping
from shapely.wkt import loads as wkt_loads

from api.schemas import JobCreate
from api.templating import make_env
from connectors.registry import Registry
from reports.manifest import BOUNDARY_STATEMENT
from reports.publisher import RightsFilter
from workers.jobs import IllegalTransition, Job, JobState, JobStore
from workers.pipeline import JobRunner

STATUS_LABELS = {
    "published": "Report ready", "awaiting_customer_input": "Select a parcel",
    "auto_publish": "Ready to publish", "qualified_output": "Ready with qualifications",
    "human_review": "Review needed", "blocked": "Publication held", "failed": "Needs attention",
}
DEMO_EXAMPLES = ("123 Main St", "500 Ocean Blvd")


def _status_label(job: Job) -> str:
    if job.state == JobState.FAILED and job.resolution and job.resolution.status == "unresolved":
        return "Property not confirmed"
    return STATUS_LABELS.get(job.state, str(job.state).replace("_", " ").title())


def build_portal_router(
    runner: JobRunner, store: JobStore, registry: Registry, *, demo_mode: bool = False,
) -> APIRouter:
    router = APIRouter()
    env = make_env()

    def _account(
        request: Request,
        x_account_id: str | None,
        account: str | None,
    ) -> str:
        acct = x_account_id or account or request.cookies.get("account")
        if not acct:
            raise HTTPException(
                400, "account required (X-Account-Id header or ?account=)"
            )
        return acct

    def _render(template: str, status: int = 200, **ctx) -> HTMLResponse:
        html = env.get_template(f"portal/{template}").render(
            boundary_statement=BOUNDARY_STATEMENT, demo_mode=demo_mode,
            examples=DEMO_EXAMPLES, status_label=_status_label, **ctx
        )
        return HTMLResponse(html, status_code=status)

    @router.get("/portal", response_class=HTMLResponse)
    def index(
        request: Request,
        x_account_id: Annotated[str | None, Header()] = None,
        account: Annotated[str | None, Query()] = None,
        retry: Annotated[str | None, Query()] = None,
        kind: Annotated[str | None, Query()] = None,
        example: Annotated[str | None, Query()] = None,
    ):
        acct = _account(request, x_account_id, account)
        values = _get_or_404(store, retry, acct).intake.model_dump() if retry else {}
        if kind in ("address", "parcel_id", "geometry"):
            values["kind"] = kind
        if demo_mode and example in DEMO_EXAMPLES:
            values = {"kind": "address", "address": example}
        return _render(
            "index.html.j2",
            jobs=sorted(store.list(acct), key=lambda job: job.updated_at, reverse=True),
            account=acct, error=None, values=values,
        )

    @router.post("/portal/jobs")
    def create_job(
        request: Request,
        kind: Annotated[str, Form()],
        address: Annotated[str | None, Form()] = None,
        unit: Annotated[str | None, Form()] = None,
        parcel_id: Annotated[str | None, Form()] = None,
        geometry_wkt: Annotated[str | None, Form()] = None,
        x_account_id: Annotated[str | None, Header()] = None,
        account: Annotated[str | None, Query()] = None,
        form_account: Annotated[str | None, Form(alias="account")] = None,
    ):
        acct = _account(request, x_account_id, account or form_account)
        try:
            intake = JobCreate(
                kind=kind,
                address=address,
                unit=unit,
                parcel_id=parcel_id,
                geometry_wkt=geometry_wkt,
            ).to_intake()
        except (ValidationError, ValueError):
            return _render(
                "index.html.j2", status=400, jobs=store.list(acct), account=acct,
                error="Check your property details. Enter an address, parcel ID or valid WKT for the selected search type.",
                values={"kind": kind, "address": address, "unit": unit,
                        "parcel_id": parcel_id, "geometry_wkt": geometry_wkt},
            )
        job = runner.submit(acct, intake)
        return RedirectResponse(
            f"/portal/jobs/{job.id}?{urlencode({'account': acct})}", status_code=303
        )

    @router.get("/portal/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(
        job_id: str,
        request: Request,
        x_account_id: Annotated[str | None, Header()] = None,
        account: Annotated[str | None, Query()] = None,
    ):
        acct = _account(request, x_account_id, account)
        job = _get_or_404(store, job_id, acct)
        candidates = _candidate_rows(job)
        not_found = bool(job.resolution and job.resolution.status == "unresolved")
        has_geometry = bool(job.resolution and any(c.geometry_wkt for c in job.resolution.candidates))
        findings = []
        withheld = 0
        known = {ds.id for ds in registry.datasets}
        for finding in job.screening.findings if job.screening else []:
            if finding.citation and (
                finding.citation.dataset_id not in known
                or not registry.dataset(finding.citation.dataset_id).permissions.allows("report")
            ):
                withheld += 1
            else:
                findings.append(finding)
        return _render(
            "job.html.j2",
            job=job,
            account=acct,
            candidates=candidates,
            imagery=RightsFilter(registry).imagery_mode(),
            JobState=JobState, not_found=not_found, findings=findings, withheld=withheld,
            has_map=has_geometry and not demo_mode and job.state != JobState.FAILED,
        )

    @router.post("/portal/jobs/{job_id}/select")
    def select_candidate(
        job_id: str,
        request: Request,
        parcel_id: Annotated[str, Form()],
        x_account_id: Annotated[str | None, Header()] = None,
        account: Annotated[str | None, Query()] = None,
        form_account: Annotated[str | None, Form(alias="account")] = None,
    ):
        acct = _account(request, x_account_id, account or form_account)
        try:
            runner.select_candidate(job_id, acct, parcel_id)
        except KeyError:
            raise HTTPException(404, "job not found") from None
        except (IllegalTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(
            f"/portal/jobs/{job_id}?{urlencode({'account': acct})}", status_code=303
        )

    @router.post("/portal/jobs/{job_id}/publish")
    def publish(job_id: str, request: Request):
        acct = _account(request, request.headers.get("X-Account-Id"), request.query_params.get("account"))
        _get_or_404(store, job_id, acct)
        try:
            runner.publish(job_id, acct)
        except (IllegalTransition, ValueError) as exc:
            raise HTTPException(409, "This report is not ready to publish.") from exc
        return RedirectResponse(
            f"/portal/jobs/{job_id}?{urlencode({'account': acct})}", status_code=303,
        )

    def published_job(job_id: str, request: Request) -> Job:
        acct = _account(request, request.headers.get("X-Account-Id"), request.query_params.get("account"))
        job = _get_or_404(store, job_id, acct)
        if job.state != JobState.PUBLISHED or not job.report:
            raise HTTPException(404, "Report not published")
        known = {ds.id for ds in registry.datasets}
        for finding in job.screening.findings if job.screening else []:
            if finding.citation and (
                finding.citation.dataset_id not in known
                or not registry.dataset(finding.citation.dataset_id).permissions.allows("report")
            ):
                raise HTTPException(403, "Report access requires a source-rights review.")
        return job

    @router.get("/portal/jobs/{job_id}/report", response_class=HTMLResponse)
    def report(job_id: str, request: Request):
        return HTMLResponse(published_job(job_id, request).report["html"])

    @router.get("/portal/jobs/{job_id}/manifest")
    def manifest(job_id: str, request: Request):
        return published_job(job_id, request).report["manifest"]

    @router.get("/portal/jobs/{job_id}/layers.geojson")
    def layers_geojson(
        job_id: str,
        request: Request,
        x_account_id: Annotated[str | None, Header()] = None,
        account: Annotated[str | None, Query()] = None,
    ):
        acct = _account(request, x_account_id, account)
        job = _get_or_404(store, job_id, acct)
        return _layers(job, registry)

    return router


def _get_or_404(store: JobStore, job_id: str, account: str) -> Job:
    try:
        return store.get(job_id, account)
    except KeyError:
        raise HTTPException(404, "job not found") from None


def _candidate_rows(job: Job) -> list[dict]:
    """Candidates plus their evidence kinds, for the picker table."""
    if not job.resolution:
        return []
    kinds: dict[str, list[str]] = {}
    for ev in job.resolution.evidence:
        kinds.setdefault(ev.candidate_parcel_id, []).append(str(ev.kind))
    return [
        {
            "parcel_id": c.parcel_id,
            "situs_address": c.situs_address,
            "unit": c.unit,
            "is_condo_unit": c.is_condo_unit,
            "evidence": kinds.get(c.parcel_id, []),
        }
        for c in job.resolution.candidates
    ]


def _feature(wkt: str | None, properties: dict) -> dict | None:
    if not wkt:
        return None
    return {
        "type": "Feature",
        "geometry": mapping(wkt_loads(wkt)),
        "properties": properties,
    }


def _layers(job: Job, registry: Registry) -> dict:
    features: list[dict] = []
    res = job.resolution
    awaiting = job.state == JobState.AWAITING_CUSTOMER_INPUT

    if awaiting and res:
        for cand in res.candidates:
            feat = _feature(
                cand.geometry_wkt,
                {
                    "layer": "candidate",
                    "dataset_id": "basemap_parcels",
                    "area": "parcel",
                    "status": "candidate",
                    "parcel_id": cand.parcel_id,
                },
            )
            if feat:
                features.append(feat)
    elif res and res.parcel_id:
        # The resolved parcel is the customer's own selection — not a
        # licensed layer — so it is always drawn.
        sel = res.customer_selection or res.parcel_id
        cand = next(
            (c for c in res.candidates if c.parcel_id == sel),
            None,
        )
        wkt = cand.geometry_wkt if cand else None
        feat = _feature(
            wkt,
            {
                "layer": "parcel",
                "dataset_id": "basemap_parcels",
                "area": "parcel",
                "status": "resolved",
                "parcel_id": res.parcel_id,
            },
        )
        if feat:
            features.append(feat)

    if job.screening:
        published = job.state == JobState.PUBLISHED
        manifest = (job.report or {}).get("manifest") or {}
        map_layers = manifest.get("map_layers") or []
        display_allowed = {
            dataset.id for dataset in registry.datasets if dataset.permissions.allows("display")
        }
        for finding in job.screening.findings:
            if not finding.citation:
                continue
            ds_id = finding.citation.dataset_id
            wkt = finding.evidence.get("geometry_wkt")
            if not wkt:
                continue
            if ds_id not in display_allowed or (published and ds_id not in map_layers):
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(wkt_loads(wkt)),
                    "properties": {
                        "layer": "evidence",
                        "dataset_id": ds_id,
                        "area": finding.area,
                        "status": str(finding.status),
                    },
                }
            )
    return {"type": "FeatureCollection", "features": features}
