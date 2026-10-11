"""SQL-backed persistence — SRS REQ-DAT-01..04.

Geometry remains WKT text inside JSON documents in this milestone; PostGIS
geometry columns arrive with the spatial-store milestone. The Job model is
stored whole as a JSON ``document`` plus indexed columns — schema-stable.

Cache rights (REQ-DAT-01): evidence pages are only persisted when the
dataset's ``cache`` permission is explicitly true; otherwise a stub row with
``page=None``/``sha256=None`` records that retention was denied — honest
about what reconstruction cannot reproduce.
"""

import hashlib
import json
from datetime import datetime
from typing import Protocol

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from connectors.contract import FeaturePage
from workers.audit import AuditEvent, AuditEventType
from workers.jobs import Job


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    registry_version: Mapped[str] = mapped_column(String)
    profile: Mapped[str] = mapped_column(String)
    profile_version: Mapped[str] = mapped_column(String)
    document: Mapped[dict] = mapped_column(JSON)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_job", "job_id"),
        Index("ix_audit_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String)
    account_id: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime)
    type: Mapped[str] = mapped_column(String)
    registry_version: Mapped[str] = mapped_column(String)
    profile: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_version: Mapped[str | None] = mapped_column(String, nullable=True)
    connector_versions: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[dict] = mapped_column(JSON)


class EvidenceRow(Base):
    __tablename__ = "evidence_artifacts"
    __table_args__ = (Index("ix_evidence_job", "job_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id"))
    dataset_id: Mapped[str] = mapped_column(String)
    authority_id: Mapped[str | None] = mapped_column(String, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    page: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


def create_schema(engine) -> None:
    Base.metadata.create_all(engine)


class SqlJobStore:
    def __init__(self, engine) -> None:
        self._engine = engine

    def get(self, id: str, account_id: str) -> Job:
        with Session(self._engine) as s:
            row = s.get(JobRow, id)
        if row is None or row.account_id != account_id:
            raise KeyError(id)
        return Job.model_validate(row.document)

    def put(self, job: Job) -> None:
        with Session(self._engine) as s:
            row = s.get(JobRow, job.id) or JobRow(id=job.id, account_id=job.account_id)
            row.account_id = job.account_id
            row.state = str(job.state)
            row.created_at = job.created_at
            row.updated_at = job.updated_at
            row.registry_version = job.registry_version
            row.profile = job.profile
            row.profile_version = job.profile_version
            row.document = job.model_dump(mode="json")
            s.merge(row)
            s.commit()

    def list(self, account_id: str) -> list[Job]:
        with Session(self._engine) as s:
            rows = (
                s.query(JobRow).filter(JobRow.account_id == account_id).all()
            )
        return [Job.model_validate(r.document) for r in rows]


class SqlAuditLog:
    def __init__(self, engine) -> None:
        self._engine = engine

    def append(self, event: AuditEvent) -> AuditEvent:
        row = AuditEventRow(
            job_id=event.job_id,
            account_id=event.account_id,
            at=event.at,
            type=str(event.type),
            registry_version=event.registry_version,
            profile=event.profile,
            profile_version=event.profile_version,
            connector_versions=event.connector_versions,
            payload=event.payload,
        )
        with Session(self._engine) as s:
            s.add(row)
            s.commit()
            event = event.model_copy(update={"id": row.id})
        return event

    def events(self, job_id: str, account_id: str) -> list[AuditEvent]:
        with Session(self._engine) as s:
            rows = (
                s.query(AuditEventRow)
                .filter(
                    AuditEventRow.job_id == job_id,
                    AuditEventRow.account_id == account_id,
                )
                .order_by(AuditEventRow.id)
                .all()
            )
        return [
            AuditEvent(
                id=r.id,
                job_id=r.job_id,
                account_id=r.account_id,
                at=r.at,
                type=AuditEventType(r.type),
                payload=r.payload,
                registry_version=r.registry_version,
                profile=r.profile,
                profile_version=r.profile_version,
                connector_versions=r.connector_versions,
            )
            for r in rows
        ]


class SqlEvidenceStore:
    def __init__(self, engine) -> None:
        self._engine = engine

    def put(
        self,
        job_id: str,
        dataset_id: str,
        authority_id: str | None,
        page: FeaturePage,
        allowed: bool,
        retrieved_at: datetime | None = None,
    ) -> None:
        if allowed:
            page_json = page.model_dump(mode="json")
            digest = hashlib.sha256(
                json.dumps(page_json, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            note = None
        else:
            page_json = None
            digest = None
            note = "cache right denied/unknown — evidence not retained"
        row = EvidenceRow(
            job_id=job_id,
            dataset_id=dataset_id,
            authority_id=authority_id,
            retrieved_at=retrieved_at,
            page=page_json,
            sha256=digest,
            note=note,
        )
        with Session(self._engine) as s:
            s.add(row)
            s.commit()

    def list(self, job_id: str) -> list[EvidenceRow]:
        with Session(self._engine) as s:
            rows = (
                s.query(EvidenceRow)
                .filter(EvidenceRow.job_id == job_id)
                .order_by(EvidenceRow.id)
                .all()
            )
            s.expunge_all()
        return rows


class EvidenceStore(Protocol):
    def put(
        self,
        job_id: str,
        dataset_id: str,
        authority_id: str | None,
        page: FeaturePage,
        allowed: bool,
        retrieved_at: datetime | None = None,
    ) -> None: ...

    def list(self, job_id: str) -> list: ...


class InMemoryEvidenceStore:
    """In-memory EvidenceStore returning detached EvidenceRow objects so the
    interface matches SqlEvidenceStore.list."""

    def __init__(self) -> None:
        self.rows: list[EvidenceRow] = []

    def put(
        self,
        job_id: str,
        dataset_id: str,
        authority_id: str | None,
        page: FeaturePage,
        allowed: bool,
        retrieved_at: datetime | None = None,
    ) -> None:
        page_json = page.model_dump(mode="json") if allowed else None
        self.rows.append(
            EvidenceRow(
                id=len(self.rows) + 1,
                job_id=job_id,
                dataset_id=dataset_id,
                authority_id=authority_id,
                retrieved_at=retrieved_at,
                page=page_json,
                sha256=(
                    hashlib.sha256(
                        json.dumps(page_json, sort_keys=True, default=str).encode()
                    ).hexdigest()
                    if allowed
                    else None
                ),
                note=(
                    None
                    if allowed
                    else "cache right denied/unknown — evidence not retained"
                ),
            )
        )

    def list(self, job_id: str) -> list[EvidenceRow]:
        return [r for r in self.rows if r.job_id == job_id]


def engine_for(url: str):
    return create_engine(url)
