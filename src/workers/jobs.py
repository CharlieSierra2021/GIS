"""Job domain model and state machine — mirrors docs/diagrams/job-lifecycle.mmd.

Framework-free: the Celery shells and the API both drive this.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from analysis.findings import ScreeningResult
from quality.gates import GateDecision
from resolution.intake import IntakeRequest
from resolution.models import ResolutionDecision


class JobState(StrEnum):
    RECEIVED = "received"
    RESOLVING = "resolving"
    AWAITING_CUSTOMER_INPUT = "awaiting_customer_input"
    ROUTING_JURISDICTION = "routing_jurisdiction"
    FETCHING = "fetching"
    SCREENING = "screening"
    QUALITY_GATES = "quality_gates"
    AUTO_PUBLISH = "auto_publish"
    QUALIFIED_OUTPUT = "qualified_output"
    HUMAN_REVIEW = "human_review"
    BLOCKED = "blocked"
    PUBLISHED = "published"
    FAILED = "failed"


_TERMINAL = {JobState.PUBLISHED, JobState.BLOCKED, JobState.FAILED}

_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.RECEIVED: {JobState.RESOLVING},
    JobState.RESOLVING: {
        JobState.AWAITING_CUSTOMER_INPUT,
        JobState.ROUTING_JURISDICTION,
    },
    JobState.AWAITING_CUSTOMER_INPUT: {JobState.RESOLVING},
    JobState.ROUTING_JURISDICTION: {JobState.FETCHING},
    JobState.FETCHING: {JobState.SCREENING},
    JobState.SCREENING: {JobState.QUALITY_GATES},
    JobState.QUALITY_GATES: {
        JobState.AUTO_PUBLISH,
        JobState.QUALIFIED_OUTPUT,
        JobState.HUMAN_REVIEW,
        JobState.BLOCKED,
    },
    JobState.HUMAN_REVIEW: {
        JobState.AUTO_PUBLISH,
        JobState.QUALIFIED_OUTPUT,
        JobState.BLOCKED,
        JobState.FETCHING,  # rescreen
    },
    JobState.AUTO_PUBLISH: {JobState.PUBLISHED, JobState.FETCHING},
    JobState.QUALIFIED_OUTPUT: {JobState.PUBLISHED, JobState.FETCHING},
    JobState.PUBLISHED: set(),
    JobState.BLOCKED: set(),
    JobState.FAILED: set(),
}
for _state, _targets in _TRANSITIONS.items():
    if _state not in _TERMINAL:
        _targets.add(JobState.FAILED)


class IllegalTransition(ValueError):
    pass


class Transition(BaseModel):
    from_state: JobState
    to_state: JobState
    at: datetime
    note: str | None = None


class Job(BaseModel):
    id: str
    account_id: str
    intake: IntakeRequest
    state: JobState = JobState.RECEIVED
    transitions: list[Transition] = []
    resolution: ResolutionDecision | None = None
    routing: dict | None = None
    screening: ScreeningResult | None = None
    gates: GateDecision | None = None
    report: dict | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    registry_version: str
    profile: str
    profile_version: str

    def advance(self, to: JobState, note: str | None = None) -> None:
        if to not in _TRANSITIONS[self.state]:
            raise IllegalTransition(
                f"{self.state} -> {to} is not a legal transition"
            )
        self.transitions.append(
            Transition(
                from_state=self.state,
                to_state=to,
                at=datetime.now(UTC),
                note=note,
            )
        )
        self.state = to
        self.updated_at = datetime.now(UTC)


class JobStore(Protocol):
    def get(self, id: str, account_id: str) -> Job: ...
    def put(self, job: Job) -> None: ...
    def list(self, account_id: str) -> list[Job]: ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, id: str, account_id: str) -> Job:
        job = self._jobs.get(id)
        if job is None or job.account_id != account_id:
            raise KeyError(id)
        return job

    def put(self, job: Job) -> None:
        self._jobs[job.id] = job

    def list(self, account_id: str) -> list[Job]:
        return [j for j in self._jobs.values() if j.account_id == account_id]
