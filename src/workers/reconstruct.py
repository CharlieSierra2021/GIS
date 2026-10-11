"""Evidence-set reconstruction — SRS REQ-AUD-01 / REQ-DAT-04.

Reassembles everything needed to reproduce a job's findings from the audit
trail and retained evidence artifacts. Reconstruction is honest about what
it cannot reproduce: datasets whose ``cache`` right is denied/unknown leave
a stub row only, and are reported in ``gaps`` rather than silently omitted.
"""

import hashlib
import json

from pydantic import BaseModel

from analysis.findings import Finding, ScreeningResult
from workers.audit import AuditEventType, AuditLog


class EvidenceArtifactOut(BaseModel):
    dataset_id: str
    authority_id: str | None = None
    retrieved_at: str | None = None
    sha256: str | None = None
    note: str | None = None


class ReconstructedFinding(BaseModel):
    finding: Finding
    artifacts: list[EvidenceArtifactOut] = []


class EvidenceSet(BaseModel):
    job_id: str
    registry_version: str
    profile: str | None = None
    profile_version: str | None = None
    resolution: dict | None = None
    routing: dict | None = None
    findings: list[ReconstructedFinding] = []
    gate_decision: dict | None = None
    manifest: dict | None = None
    complete: bool
    gaps: list[str] = []


def _artifact(row) -> EvidenceArtifactOut:
    return EvidenceArtifactOut(
        dataset_id=row.dataset_id,
        authority_id=row.authority_id,
        retrieved_at=(
            row.retrieved_at.isoformat() if row.retrieved_at else None
        ),
        sha256=row.sha256,
        note=row.note,
    )


def reconstruct_evidence_set(
    job_id: str, account_id: str, audit: AuditLog, evidence
) -> EvidenceSet:
    events = audit.events(job_id, account_id)

    screening = None
    routing = None
    resolution = None
    gate_decision = None
    manifest = None
    registry_version = ""
    profile = profile_version = None

    for e in events:
        registry_version = e.registry_version
        profile = e.profile
        profile_version = e.profile_version
        if e.type == AuditEventType.SCREENING:
            screening = ScreeningResult.model_validate(e.payload["screening"])
        elif e.type == AuditEventType.ROUTING:
            routing = e.payload.get("routing")
        elif e.type == AuditEventType.RESOLUTION:
            resolution = e.payload.get("decision")
        elif e.type == AuditEventType.GATE_DECISION:
            gate_decision = e.payload.get("decision")
        elif e.type == AuditEventType.PUBLISHED:
            manifest = e.payload.get("manifest")

    artifacts = evidence.list(job_id)
    by_dataset: dict[str, list] = {}
    for row in artifacts:
        by_dataset.setdefault(row.dataset_id, []).append(row)

    findings: list[ReconstructedFinding] = []
    gaps: list[str] = []
    if screening:
        for finding in screening.findings:
            ds_id = finding.citation.dataset_id if finding.citation else None
            rows = by_dataset.get(ds_id, []) if ds_id else []
            findings.append(
                ReconstructedFinding(
                    finding=finding,
                    artifacts=[_artifact(r) for r in rows],
                )
            )
            if (
                finding.status.value == "present"
                and ds_id
                and not any(r.sha256 for r in rows)
                and ds_id not in gaps
            ):
                gaps.append(ds_id)

    return EvidenceSet(
        job_id=job_id,
        registry_version=registry_version,
        profile=profile,
        profile_version=profile_version,
        resolution=resolution,
        routing=routing,
        findings=findings,
        gate_decision=gate_decision,
        manifest=manifest,
        complete=not gaps,
        gaps=sorted(gaps),
    )


def page_sha256(page_json: dict) -> str:
    """Recompute the digest stored alongside a retained evidence page."""
    return hashlib.sha256(
        json.dumps(page_json, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
