"""Audit trail — SRS REQ-DAT-04, REQ-AUD-01, REQ-QG-04.

Append-only: every decision artefact is recorded so a report can be
reconstructed (which source version, connector version, registry version,
profile version produced each finding). The protocol exposes no update or
delete methods.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class AuditEventType(StrEnum):
    JOB_CREATED = "job_created"
    TRANSITION = "transition"
    RESOLUTION = "resolution"
    ROUTING = "routing"
    SCREENING = "screening"
    GATE_RESULT = "gate_result"
    GATE_DECISION = "gate_decision"
    REVIEW = "review"
    PUBLISHED = "published"
    ERROR = "error"


class AuditEvent(BaseModel):
    id: int | None = None
    job_id: str
    account_id: str
    at: datetime
    type: AuditEventType
    payload: dict
    registry_version: str
    profile: str | None = None
    profile_version: str | None = None
    connector_versions: dict = {}


class AuditLog(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent: ...
    def events(self, job_id: str, account_id: str) -> list[AuditEvent]: ...


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._next_id = 1

    def append(self, event: AuditEvent) -> AuditEvent:
        event = event.model_copy(update={"id": self._next_id})
        self._next_id += 1
        self._events.append(event)
        return event

    def events(self, job_id: str, account_id: str) -> list[AuditEvent]:
        return [
            e
            for e in self._events
            if e.job_id == job_id and e.account_id == account_id
        ]
