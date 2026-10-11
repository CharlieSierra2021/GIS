"""JobRunner — drives a job through the lifecycle state machine."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from shapely import from_wkt

from analysis.engine import EvidenceFetcher, ScreeningContext, screen
from analysis.profile import Profile
from connectors.registry import Registry
from jurisdiction.router import JurisdictionRouter, RoutingStatus
from quality.gates import Disposition, GateInputs, apply_review, evaluate
from resolution.models import ResolutionStatus
from resolution.resolver import ParcelResolver
from workers.jobs import (
    IllegalTransition,
    Job,
    JobState,
    JobStore,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


_DISPOSITION_STATE = {
    Disposition.AUTO_PUBLISH: JobState.AUTO_PUBLISH,
    Disposition.QUALIFIED_OUTPUT: JobState.QUALIFIED_OUTPUT,
    Disposition.HUMAN_REVIEW: JobState.HUMAN_REVIEW,
    Disposition.BLOCKED: JobState.BLOCKED,
}


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        resolver: ParcelResolver,
        router: JurisdictionRouter | None,
        fetcher: EvidenceFetcher,
        registry: Registry,
        profile: Profile,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._resolver = resolver
        self._router = router
        self._fetcher = fetcher
        self._registry = registry
        self._profile = profile
        self._clock = clock

    @property
    def store(self) -> JobStore:
        return self._store

    # -- public API ---------------------------------------------------------

    def submit(self, account_id: str, intake) -> Job:
        now = self._clock()
        job = Job(
            id=str(uuid.uuid4()),
            account_id=account_id,
            intake=intake,
            created_at=now,
            updated_at=now,
            registry_version=self._registry.registry_version,
            profile=self._profile.profile,
            profile_version=self._profile.version,
        )
        self._store.put(job)
        return self.run(job.id, account_id)

    def run(self, job_id: str, account_id: str) -> Job:
        job = self._store.get(job_id, account_id)
        if job.state == JobState.AWAITING_CUSTOMER_INPUT:
            return job
        try:
            job.advance(JobState.RESOLVING)
            decision = self._resolver.resolve(job.intake)
            job.resolution = decision
            if decision.status == ResolutionStatus.AWAITING_CUSTOMER_INPUT:
                job.advance(
                    JobState.AWAITING_CUSTOMER_INPUT,
                    note=decision.disclosure,
                )
            elif decision.status == ResolutionStatus.UNRESOLVED:
                raise RuntimeError(decision.disclosure or "parcel unresolved")
            else:
                self._continue(job)
        except IllegalTransition:
            raise
        except Exception as exc:  # noqa: BLE001 - job must fail, not crash
            if job.state != JobState.FAILED:
                job.error = str(exc)
                try:
                    job.advance(JobState.FAILED, note=str(exc))
                except IllegalTransition:
                    job.state = JobState.FAILED
        finally:
            self._store.put(job)
        return job

    def select_candidate(
        self, job_id: str, account_id: str, parcel_id: str
    ) -> Job:
        job = self._store.get(job_id, account_id)
        if job.state != JobState.AWAITING_CUSTOMER_INPUT:
            raise IllegalTransition(
                f"select_candidate requires state "
                f"{JobState.AWAITING_CUSTOMER_INPUT}, got {job.state}"
            )
        try:
            job.resolution = self._resolver.confirm(job.resolution, parcel_id)
            job.advance(
                JobState.RESOLVING, note=f"customer selected {parcel_id}"
            )
            self._continue(job)
        except (IllegalTransition, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001 - job must fail, not crash
            job.error = str(exc)
            try:
                job.advance(JobState.FAILED, note=str(exc))
            except IllegalTransition:
                job.state = JobState.FAILED
        finally:
            self._store.put(job)
        return job

    def review(
        self,
        job_id: str,
        account_id: str,
        reviewer: str,
        approve: str,
        rationale: str,
    ) -> Job:
        job = self._store.get(job_id, account_id)
        if job.state != JobState.HUMAN_REVIEW:
            raise IllegalTransition(
                f"review requires state {JobState.HUMAN_REVIEW}, got {job.state}"
            )
        job.gates = apply_review(job.gates, reviewer, approve, rationale)
        job.advance(
            _DISPOSITION_STATE[job.gates.disposition],
            note=f"reviewer {reviewer}: {approve} — {rationale}",
        )
        self._store.put(job)
        return job

    # -- internals ----------------------------------------------------------

    def _continue(self, job: Job) -> None:
        job.advance(JobState.ROUTING_JURISDICTION)
        routing = self._route(job)
        job.routing = routing

        job.advance(JobState.FETCHING)
        job.advance(JobState.SCREENING)
        authority_id = (
            routing["authority_id"] if routing["status"] == "resolved" else None
        )
        ctx = ScreeningContext(
            job_id=job.id,
            parcel_id=job.resolution.parcel_id,
            parcel_wkt=self._parcel_wkt(job),
            registry=self._registry,
            authority_id=authority_id,
            now=self._clock(),
        )
        job.screening = screen(ctx, self._profile, self._fetcher)

        job.advance(JobState.QUALITY_GATES)
        job.gates = evaluate(
            GateInputs(
                resolution=job.resolution,
                screening=job.screening,
                registry=self._registry,
                now=self._clock(),
                conflicts=[],
            )
        )
        job.advance(_DISPOSITION_STATE[job.gates.disposition])

    def _route(self, job: Job) -> dict:
        wkt = self._parcel_wkt(job)
        if self._router is None:
            return {
                "status": RoutingStatus.UNRESOLVED,
                "authority_id": None,
                "candidates": (),
                "disclosure": (
                    "authority boundaries not loaded; jurisdiction withheld"
                ),
                "evidence": {},
            }
        if wkt is None:
            return {
                "status": RoutingStatus.UNRESOLVED,
                "authority_id": None,
                "candidates": (),
                "disclosure": (
                    "resolved parcel has no geometry; jurisdiction withheld"
                ),
                "evidence": {},
            }
        result = self._router.route(from_wkt(wkt))
        return {
            "status": result.status,
            "authority_id": result.authority_id,
            "candidates": result.candidates,
            "disclosure": result.disclosure,
            "evidence": result.evidence,
        }

    @staticmethod
    def _parcel_wkt(job: Job) -> str | None:
        if job.resolution is None:
            return None
        for cand in job.resolution.candidates:
            if cand.parcel_id == job.resolution.parcel_id:
                return cand.geometry_wkt
        return None
