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
from workers.audit import AuditEvent, AuditEventType, AuditLog
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
        publisher=None,
        auto_publish_on_pass: bool = False,
        audit: AuditLog | None = None,
        evidence_store=None,
    ) -> None:
        self._store = store
        self._resolver = resolver
        self._router = router
        self._fetcher = fetcher
        self._registry = registry
        self._profile = profile
        self._clock = clock
        self._publisher = publisher
        self._auto_publish_on_pass = auto_publish_on_pass
        self._audit = audit
        self._evidence_store = evidence_store

    @property
    def store(self) -> JobStore:
        return self._store

    @property
    def audit(self):
        return self._audit

    @property
    def evidence_store(self):
        return self._evidence_store

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
        self._emit(
            job, AuditEventType.JOB_CREATED, {"intake": intake.model_dump(mode="json")}
        )
        return self.run(job.id, account_id)

    def run(self, job_id: str, account_id: str) -> Job:
        job = self._store.get(job_id, account_id)
        if job.state == JobState.AWAITING_CUSTOMER_INPUT:
            return job
        try:
            self._advance(job, JobState.RESOLVING)
            decision = self._resolver.resolve(job.intake)
            job.resolution = decision
            self._emit(
                job,
                AuditEventType.RESOLUTION,
                {"decision": decision.model_dump(mode="json")},
            )
            if decision.status == ResolutionStatus.AWAITING_CUSTOMER_INPUT:
                self._advance(
                    job,
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
                    self._advance(job, JobState.FAILED, note=str(exc))
                except IllegalTransition:
                    job.state = JobState.FAILED
                self._emit(job, AuditEventType.ERROR, {"error": str(exc)})
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
            self._emit(
                job,
                AuditEventType.RESOLUTION,
                {
                    "decision": job.resolution.model_dump(mode="json"),
                    "customer_selection": parcel_id,
                },
            )
            self._advance(
                job, JobState.RESOLVING, note=f"customer selected {parcel_id}"
            )
            self._continue(job)
        except (IllegalTransition, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001 - job must fail, not crash
            job.error = str(exc)
            try:
                self._advance(job, JobState.FAILED, note=str(exc))
            except IllegalTransition:
                job.state = JobState.FAILED
            self._emit(job, AuditEventType.ERROR, {"error": str(exc)})
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
        self._emit(
            job,
            AuditEventType.REVIEW,
            {"reviewer": reviewer, "approve": approve, "rationale": rationale},
        )
        self._advance(
            job,
            _DISPOSITION_STATE[job.gates.disposition],
            note=f"reviewer {reviewer}: {approve} — {rationale}",
        )
        self._store.put(job)
        return job

    def publish(self, job_id: str, account_id: str) -> Job:
        job = self._store.get(job_id, account_id)
        if job.state not in (JobState.AUTO_PUBLISH, JobState.QUALIFIED_OUTPUT):
            raise IllegalTransition(
                f"publish requires state {JobState.AUTO_PUBLISH} or "
                f"{JobState.QUALIFIED_OUTPUT}, got {job.state}"
            )
        self._do_publish(job)
        self._store.put(job)
        return job

    def _do_publish(self, job: Job) -> None:
        if self._publisher is None:
            raise ValueError("no report publisher configured")
        published = self._publisher.publish(job)
        job.report = {
            "manifest": published.manifest.model_dump(mode="json"),
            "html": published.html,
        }
        self._emit(
            job,
            AuditEventType.PUBLISHED,
            {"manifest": published.manifest.model_dump(mode="json")},
        )
        self._advance(job, JobState.PUBLISHED, note="report rendered + manifest")

    # -- internals ----------------------------------------------------------

    def _advance(self, job: Job, to: JobState, note: str | None = None) -> None:
        job.advance(to, note=note)
        t = job.transitions[-1]
        self._emit(
            job,
            AuditEventType.TRANSITION,
            {"from": str(t.from_state), "to": str(t.to_state), "note": note},
        )

    def _emit(self, job: Job, type: AuditEventType, payload: dict) -> None:
        if self._audit is None:
            return
        self._audit.append(
            AuditEvent(
                job_id=job.id,
                account_id=job.account_id,
                at=self._clock(),
                type=type,
                payload=payload,
                registry_version=job.registry_version,
                profile=job.profile,
                profile_version=job.profile_version,
            )
        )

    def _continue(self, job: Job) -> None:
        self._advance(job, JobState.ROUTING_JURISDICTION)
        routing = self._route(job)
        job.routing = routing
        self._emit(job, AuditEventType.ROUTING, {"routing": routing})

        self._advance(job, JobState.FETCHING)
        self._advance(job, JobState.SCREENING)
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
        fetcher = self._fetcher
        if self._evidence_store is not None:
            fetcher = RecordingFetcher(
                self._fetcher, self._evidence_store, self._registry, job.id
            )
        job.screening = screen(ctx, self._profile, fetcher)
        self._emit(
            job,
            AuditEventType.SCREENING,
            {"screening": job.screening.model_dump(mode="json")},
        )

        self._advance(job, JobState.QUALITY_GATES)
        job.gates = evaluate(
            GateInputs(
                resolution=job.resolution,
                screening=job.screening,
                registry=self._registry,
                now=self._clock(),
                conflicts=[],
            )
        )
        for gate in job.gates.gates:
            self._emit(
                job,
                AuditEventType.GATE_RESULT,
                {"gate": gate.model_dump(mode="json")},
            )
        self._emit(
            job,
            AuditEventType.GATE_DECISION,
            {"decision": job.gates.model_dump(mode="json")},
        )
        self._advance(job, _DISPOSITION_STATE[job.gates.disposition])
        if (
            self._auto_publish_on_pass
            and self._publisher is not None
            and job.gates.disposition == Disposition.AUTO_PUBLISH
        ):
            self._do_publish(job)

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


class RecordingFetcher:
    """Wraps an EvidenceFetcher and stores each returned FeaturePage in the
    evidence store (subject to the dataset's cache right) before returning it."""

    def __init__(self, inner, evidence_store, registry, job_id: str) -> None:
        self._inner = inner
        self._store = evidence_store
        self._registry = registry
        self._job_id = job_id

    def fetch(
        self, dataset_id, parcel_wkt, spatial_rel, buffer_m, authority_id=None
    ):
        page = self._inner.fetch(
            dataset_id, parcel_wkt, spatial_rel, buffer_m, authority_id
        )
        dataset = self._registry.dataset(dataset_id)
        allowed = dataset.permissions.allows("cache")
        retrieved = (
            page.features[0].provenance.retrieved_at if page.features else None
        )
        self._store.put(
            self._job_id, dataset_id, authority_id, page,
            allowed=allowed, retrieved_at=retrieved,
        )
        return page
