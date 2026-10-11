"""Quality gates — SRS REQ-QG-01..04, ICD §15.

Evaluated before publication. Every gate is recorded even after a block
(REQ-QG-04); auto-publish requires all five gates to pass. License and
parcel-identity blocks are hard: review cannot override them.

Cross-source conflicts are supplied by the caller in ``GateInputs.conflicts``;
entries prefixed ``"material:"`` denote identity/geometry-grade
contradictions (convention until the conflict model lands).
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from analysis.findings import FindingStatus, ScreeningResult
from connectors.registry import Registry
from resolution.models import ConfidenceClass, ResolutionDecision, ResolutionStatus


class Disposition(StrEnum):
    AUTO_PUBLISH = "auto_publish"
    QUALIFIED_OUTPUT = "qualified_output"
    HUMAN_REVIEW = "human_review"
    BLOCKED = "blocked"


class GateOutcome(StrEnum):
    PASS = "pass"
    QUALIFIED = "qualified"
    REVIEW = "review"
    BLOCKED = "blocked"


class GateResult(BaseModel):
    gate: Literal["parcel_identity", "license", "freshness", "coverage", "conflict"]
    outcome: GateOutcome
    reasons: list[str] = []
    inputs: dict = {}


class GateDecision(BaseModel):
    disposition: Disposition
    gates: list[GateResult]
    qualifications: list[str] = []
    evaluated_at: datetime
    review: dict | None = None


class GateInputs(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    resolution: ResolutionDecision
    screening: ScreeningResult
    registry: Registry
    now: datetime
    conflicts: list[str] = []


def _gate_parcel_identity(inputs: GateInputs) -> GateResult:
    res = inputs.resolution
    ok = res.status == ResolutionStatus.RESOLVED and res.confidence in (
        ConfidenceClass.IDENTITY,
        ConfidenceClass.STRONG,
    )
    return GateResult(
        gate="parcel_identity",
        outcome=GateOutcome.PASS if ok else GateOutcome.BLOCKED,
        reasons=[]
        if ok
        else [
            (
                f"parcel identity unresolved: status={res.status} "
                f"confidence={res.confidence}"
            )
        ],
        inputs={"status": str(res.status), "confidence": str(res.confidence)},
    )


def _gate_license(inputs: GateInputs) -> GateResult:
    reasons: list[str] = []
    for finding in inputs.screening.findings:
        if finding.citation is None:
            continue
        ds = inputs.registry.dataset(finding.citation.dataset_id)
        if not ds.permissions.allows("report"):
            reasons.append(
                f"dataset {ds.id}: report right denied/unknown "
                f"(finding {finding.id})"
            )
        if finding.evidence.get("geometry_wkt") and not ds.permissions.allows(
            "display"
        ):
            reasons.append(
                f"dataset {ds.id}: display right denied/unknown for geometry "
                f"evidence (finding {finding.id})"
            )
    return GateResult(
        gate="license",
        outcome=GateOutcome.BLOCKED if reasons else GateOutcome.PASS,
        reasons=reasons,
    )


def _gate_freshness(inputs: GateInputs) -> GateResult:
    stale_mandatory: list[str] = []
    stale_other: list[str] = []
    for finding in inputs.screening.findings:
        if finding.status not in (FindingStatus.PRESENT, FindingStatus.NOT_FOUND):
            continue
        if finding.citation is None:
            continue
        ds = inputs.registry.dataset(finding.citation.dataset_id)
        policy = ds.freshness
        if policy is None or policy.max_age_days is None:
            continue
        retrieved = finding.citation.retrieved_at
        stale = (
            retrieved is None
            or (inputs.now - retrieved).days > policy.max_age_days
        )
        if stale:
            msg = (
                f"dataset {ds.id} stale for finding {finding.id} "
                f"(max_age_days={policy.max_age_days})"
            )
            (stale_mandatory if finding.mandatory else stale_other).append(msg)
    if stale_mandatory:
        return GateResult(
            gate="freshness",
            outcome=GateOutcome.REVIEW,
            reasons=stale_mandatory,
        )
    if stale_other:
        return GateResult(
            gate="freshness",
            outcome=GateOutcome.QUALIFIED,
            reasons=stale_other,
        )
    return GateResult(gate="freshness", outcome=GateOutcome.PASS)


def _gate_coverage(inputs: GateInputs) -> GateResult:
    gaps: list[str] = []
    partial: list[str] = []
    for finding in inputs.screening.findings:
        if finding.status == FindingStatus.NOT_ASSESSED:
            msg = f"finding {finding.id} not assessed ({finding.disclosure})"
            (gaps if finding.mandatory else partial).append(msg)
        elif finding.status == FindingStatus.PENDING:
            req = finding.evidence.get("request_id", "unknown")
            msg = f"{finding.area} pending records request {req}"
            # Mandatory pending goes to review — the SLA cannot auto-pass
            # it; non-mandatory is disclosed as a qualification.
            (gaps if finding.mandatory else partial).append(msg)
        elif finding.status == FindingStatus.NOT_FOUND:
            partial.append(f"finding {finding.id}: no record, disclosed")
    if gaps:
        return GateResult(gate="coverage", outcome=GateOutcome.REVIEW, reasons=gaps)
    if partial:
        return GateResult(
            gate="coverage", outcome=GateOutcome.QUALIFIED, reasons=partial
        )
    return GateResult(gate="coverage", outcome=GateOutcome.PASS)


def _gate_conflict(inputs: GateInputs) -> GateResult:
    material = [c for c in inputs.conflicts if c.startswith("material:")]
    minor = [c for c in inputs.conflicts if not c.startswith("material:")]
    if material:
        return GateResult(
            gate="conflict", outcome=GateOutcome.REVIEW, reasons=material
        )
    if minor:
        return GateResult(
            gate="conflict", outcome=GateOutcome.QUALIFIED, reasons=minor
        )
    return GateResult(gate="conflict", outcome=GateOutcome.PASS)


def evaluate(inputs: GateInputs) -> GateDecision:
    gates = [
        _gate_parcel_identity(inputs),
        _gate_license(inputs),
        _gate_freshness(inputs),
        _gate_coverage(inputs),
        _gate_conflict(inputs),
    ]
    outcomes = {g.outcome for g in gates}
    if GateOutcome.BLOCKED in outcomes:
        disposition = Disposition.BLOCKED
    elif GateOutcome.REVIEW in outcomes:
        disposition = Disposition.HUMAN_REVIEW
    elif GateOutcome.QUALIFIED in outcomes:
        disposition = Disposition.QUALIFIED_OUTPUT
    else:
        disposition = Disposition.AUTO_PUBLISH
    return GateDecision(
        disposition=disposition,
        gates=gates,
        qualifications=[
            r for g in gates if g.outcome == GateOutcome.QUALIFIED for r in g.reasons
        ],
        evaluated_at=inputs.now,
    )


def apply_review(
    decision: GateDecision,
    reviewer: str,
    approve: Literal["publish", "qualified", "reject"],
    rationale: str,
) -> GateDecision:
    if decision.disposition == Disposition.BLOCKED:
        raise ValueError(
            "blocked decisions cannot be overridden by review "
            "(license/identity blocks are hard)"
        )
    if decision.disposition != Disposition.HUMAN_REVIEW:
        raise ValueError(
            f"apply_review requires disposition {Disposition.HUMAN_REVIEW}, "
            f"got {decision.disposition}"
        )
    decision.disposition = {
        "publish": Disposition.AUTO_PUBLISH,
        "qualified": Disposition.QUALIFIED_OUTPUT,
        "reject": Disposition.BLOCKED,
    }[approve]
    decision.review = {
        "reviewer": reviewer,
        "outcome": approve,
        "rationale": rationale,
    }
    return decision
