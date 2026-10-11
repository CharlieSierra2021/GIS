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


def build_portal_router(
    runner: JobRunner, store: JobStore, registry: Registry
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
            boundary_statement=BOUNDARY_STATEMENT, **ctx
        )
        return HTMLResponse(html, status_code=status)

    @router.get("/portal", response_class=HTMLResponse)
    def index(
        request: Request,
        x_account_id: Annotated[str | None, Header()] = None,
        account: Annotated[str | None, Query()] = None,
        error: Annotated[str | None, Query()] = None,
    ):
        acct = _account(request, x_account_id, account)
        return _render(
            "index.html.j2",
            jobs=store.list(acct),
            account=acct,
            error=error,
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
        except (ValidationError, ValueError) as exc:
            return _render(
                "index.html.j2",
                status=400,
                jobs=store.list(acct),
                account=acct,
                error=str(exc),
            )
        job = runner.submit(acct, intake)
        return RedirectResponse(
            f"/portal/jobs/{job.id}?account={acct}", status_code=303
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
        return _render(
            "job.html.j2",
            job=job,
            account=acct,
            candidates=candidates,
            imagery=RightsFilter(registry).imagery_mode(),
            JobState=JobState,
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
            f"/portal/jobs/{job_id}?account={acct}", status_code=303
        )

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
        published = job.state == JobState.PUBLISHED and job.report
        map_layers = (
            job.report["manifest"].get("map_layers", []) if published else []
        )
        for finding in job.screening.findings:
            if not finding.citation:
                continue
            ds_id = finding.citation.dataset_id
            wkt = finding.evidence.get("geometry_wkt")
            if not wkt:
                continue
            if published:
                allowed = ds_id in map_layers
            else:
                allowed = registry.dataset(ds_id).permissions.allows("display")
            if not allowed:
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
