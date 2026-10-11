"""Job + portfolio endpoints. Account id arrives as X-Account-Id header
(real auth is a later milestone; REQ-SEC-03 isolation is enforced by the
store regardless)."""

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from api.schemas import (
    CandidateSelect,
    JobCreate,
    RecordsRequestUpdate,
    ReviewDecision,
    job_out,
)
from connectors.records_request import RequestStatus
from workers.jobs import IllegalTransition, JobStore
from workers.pipeline import JobRunner
from workers.reconstruct import reconstruct_evidence_set


def build_router(
    runner: JobRunner, store: JobStore, audit=None, evidence_store=None
) -> APIRouter:
    router = APIRouter()

    def _account(x_account_id: Annotated[str | None, Header()]) -> str:
        if not x_account_id:
            raise HTTPException(400, "X-Account-Id header required")
        return x_account_id

    @router.post("/jobs", status_code=201)
    def create_job(
        body: JobCreate,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            return job_out(runner.submit(account, body.to_intake()))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/jobs")
    def list_jobs(x_account_id: Annotated[str | None, Header()] = None):
        account = _account(x_account_id)
        return [job_out(j) for j in store.list(account)]

    @router.get("/jobs/{job_id}")
    def get_job(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            return job_out(store.get(job_id, account))
        except KeyError:
            raise HTTPException(404, "job not found") from None

    @router.post("/jobs/{job_id}/select-candidate")
    def select_candidate(
        job_id: str,
        body: CandidateSelect,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            return job_out(
                runner.select_candidate(job_id, account, body.parcel_id)
            )
        except KeyError:
            raise HTTPException(404, "job not found") from None
        except (IllegalTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/jobs/{job_id}/review")
    def review_job(
        job_id: str,
        body: ReviewDecision,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            return job_out(
                runner.review(
                    job_id, account, body.reviewer, body.approve, body.rationale
                )
            )
        except KeyError:
            raise HTTPException(404, "job not found") from None
        except (IllegalTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/jobs/{job_id}/publish")
    def publish_job(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            return job_out(runner.publish(job_id, account))
        except KeyError:
            raise HTTPException(404, "job not found") from None
        except (IllegalTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/jobs/{job_id}/report")
    def get_report(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            job = store.get(job_id, account)
        except KeyError:
            raise HTTPException(404, "job not found") from None
        if not job.report:
            raise HTTPException(404, "report not published")
        return HTMLResponse(job.report["html"])

    @router.get("/jobs/{job_id}/manifest")
    def get_manifest(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            job = store.get(job_id, account)
        except KeyError:
            raise HTTPException(404, "job not found") from None
        if not job.report:
            raise HTTPException(404, "report not published")
        return job.report["manifest"]

    @router.get("/jobs/{job_id}/audit")
    def get_audit(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            store.get(job_id, account)
        except KeyError:
            raise HTTPException(404, "job not found") from None
        events = audit.events(job_id, account) if audit else []
        return [e.model_dump(mode="json") for e in events]

    @router.get("/jobs/{job_id}/evidence")
    def get_evidence(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            store.get(job_id, account)
        except KeyError:
            raise HTTPException(404, "job not found") from None
        return reconstruct_evidence_set(
            job_id, account, audit, evidence_store
        ).model_dump(mode="json")

    @router.post("/jobs/{job_id}/rescreen")
    def rescreen_job(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            return job_out(runner.rescreen(job_id, account))
        except KeyError:
            raise HTTPException(404, "job not found") from None
        except (IllegalTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/records-requests")
    def list_records_requests(
        job_id: str,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        try:
            store.get(job_id, account)
        except KeyError:
            raise HTTPException(404, "job not found") from None
        tracker = runner.records_tracker
        if tracker is None:
            return []
        return [
            r.model_dump(mode="json") for r in tracker.list_by_job(job_id)
        ]

    @router.post("/records-requests/{request_id}")
    def update_records_request(
        request_id: str,
        body: RecordsRequestUpdate,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        _account(x_account_id)
        tracker = runner.records_tracker
        if tracker is None:
            raise HTTPException(404, "records tracking not configured")
        try:
            status = RequestStatus(body.status)
        except ValueError:
            raise HTTPException(422, f"invalid status {body.status}") from None
        try:
            req = tracker.update(
                request_id,
                status=status,
                documents=body.documents,
                note=body.note,
            )
        except KeyError:
            raise HTTPException(404, "records request not found") from None
        return req.model_dump(mode="json")

    @router.post("/portfolios", status_code=201)
    async def create_portfolio(
        file: UploadFile,
        x_account_id: Annotated[str | None, Header()] = None,
    ):
        account = _account(x_account_id)
        text = (await file.read()).decode("utf-8")
        results = []
        for i, row in enumerate(csv.DictReader(io.StringIO(text))):
            try:
                intake = JobCreate(**row).to_intake()
                job = runner.submit(account, intake)
                results.append({"row": i, "job_id": job.id, "state": str(job.state)})
            except Exception as exc:  # noqa: BLE001 - one bad row never aborts
                results.append({"row": i, "error": str(exc)})
        return {"results": results}

    return router
