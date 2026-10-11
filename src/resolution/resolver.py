"""Parcel resolver — SRS REQ-RES-01..06.

Resolution is a decision over evidence classes (parcel-ID match, address
match, unit match, geometry match, point-in-polygon), never a heuristic.
A point in a polygon alone never resolves (REQ-RES-02); multiple plausible
candidates always suspend to AwaitingCustomerInput (REQ-RES-03); no silent
tie-break of any kind (REQ-RES-04).
"""

import re
from typing import Protocol

from resolution.geometry import iou, parse_wkt
from resolution.intake import IntakeKind, IntakeRequest, normalize_address
from resolution.models import (
    ConfidenceClass,
    Evidence,
    EvidenceKind,
    ParcelCandidate,
    ResolutionDecision,
    ResolutionStatus,
)

_GEOMETRY_IOU_THRESHOLD = 0.95

# Ordering used only to report which prior evidence a customer confirmation
# reaffirms — never to choose a candidate.
_KIND_RANK = {
    EvidenceKind.PARCEL_ID_EXACT: 0,
    EvidenceKind.UNIT_EXACT: 1,
    EvidenceKind.ADDRESS_EXACT: 2,
    EvidenceKind.GEOMETRY_MATCH: 3,
    EvidenceKind.ADDRESS_FUZZY: 4,
    EvidenceKind.POINT_IN_POLYGON: 5,
}


class ParcelSource(Protocol):
    def by_parcel_id(self, pid: str) -> list[ParcelCandidate]: ...

    def by_address(self, street_normalized: str) -> list[ParcelCandidate]:
        """All candidates sharing the normalized street address —
        every condo unit at that situs included."""
        ...

    def intersecting(self, geometry_wkt: str) -> list[ParcelCandidate]: ...

    def containing_point(self, x: float, y: float) -> list[ParcelCandidate]: ...


def _norm_unit(u: str | None) -> str | None:
    if u is None:
        return None
    text = re.sub(r"[^\w\s#]", " ", u.upper())
    text = re.sub(r"\b(APT|UNIT|STE)\b", " ", text)
    return re.sub(r"[\s#]+", "", text) or None


class ParcelResolver:
    def __init__(self, source: ParcelSource) -> None:
        self._source = source

    def resolve(self, req: IntakeRequest) -> ResolutionDecision:
        if req.kind == IntakeKind.PARCEL_ID:
            return self._resolve_parcel_id(req)
        if req.kind == IntakeKind.ADDRESS:
            return self._resolve_address(req)
        return self._resolve_geometry(req)

    def _resolve_parcel_id(self, req: IntakeRequest) -> ResolutionDecision:
        found = self._source.by_parcel_id(req.parcel_id)
        if len(found) == 1:
            cand = found[0]
            return ResolutionDecision(
                status=ResolutionStatus.RESOLVED,
                parcel_id=cand.parcel_id,
                confidence=ConfidenceClass.IDENTITY,
                candidates=[cand],
                evidence=[
                    Evidence(
                        kind=EvidenceKind.PARCEL_ID_EXACT,
                        candidate_parcel_id=cand.parcel_id,
                        detail={"input": req.parcel_id},
                    )
                ],
            )
        if not found:
            return ResolutionDecision(
                status=ResolutionStatus.UNRESOLVED,
                disclosure=f"No parcel found for id {req.parcel_id!r}.",
            )
        return ResolutionDecision(
            status=ResolutionStatus.AWAITING_CUSTOMER_INPUT,
            candidates=found,
            evidence=[
                Evidence(
                    kind=EvidenceKind.PARCEL_ID_EXACT,
                    candidate_parcel_id=c.parcel_id,
                    detail={"input": req.parcel_id},
                )
                for c in found
            ],
            disclosure="Parcel id matched multiple records; confirm the parcel.",
        )

    def _resolve_address(self, req: IntakeRequest) -> ResolutionDecision:
        normalized = normalize_address(req.address)
        found = self._source.by_address(normalized.street)
        unit = _norm_unit(req.unit) or _norm_unit(normalized.unit)
        if not found:
            return ResolutionDecision(
                status=ResolutionStatus.UNRESOLVED,
                disclosure=f"No parcel found at situs {normalized.street!r}.",
            )
        if len(found) == 1:
            cand = found[0]
            cand_unit = _norm_unit(cand.unit)
            if unit is not None and cand_unit is not None and cand_unit != unit:
                return ResolutionDecision(
                    status=ResolutionStatus.AWAITING_CUSTOMER_INPUT,
                    candidates=found,
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.ADDRESS_EXACT,
                            candidate_parcel_id=cand.parcel_id,
                            detail={"street": normalized.street},
                        )
                    ],
                    disclosure=(
                        f"Requested unit {unit} does not match the only parcel at "
                        f"this situs (unit {cand_unit}); confirm the parcel."
                    ),
                )
            detail = {"street": normalized.street}
            if unit is not None and cand_unit is None:
                detail["requested_unit_ignored"] = unit
            return ResolutionDecision(
                status=ResolutionStatus.RESOLVED,
                parcel_id=cand.parcel_id,
                confidence=ConfidenceClass.IDENTITY,
                candidates=[cand],
                evidence=[
                    Evidence(
                        kind=EvidenceKind.ADDRESS_EXACT,
                        candidate_parcel_id=cand.parcel_id,
                        detail=detail,
                    )
                ],
            )

        if unit is not None:
            matched = [c for c in found if _norm_unit(c.unit) == unit]
            if len(matched) == 1:
                cand = matched[0]
                return ResolutionDecision(
                    status=ResolutionStatus.RESOLVED,
                    parcel_id=cand.parcel_id,
                    confidence=ConfidenceClass.IDENTITY,
                    candidates=[cand],
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.ADDRESS_EXACT,
                            candidate_parcel_id=cand.parcel_id,
                            detail={"street": normalized.street},
                        ),
                        Evidence(
                            kind=EvidenceKind.UNIT_EXACT,
                            candidate_parcel_id=cand.parcel_id,
                            detail={"unit": unit},
                        ),
                    ],
                )

        return ResolutionDecision(
            status=ResolutionStatus.AWAITING_CUSTOMER_INPUT,
            candidates=found,
            evidence=[
                Evidence(
                    kind=EvidenceKind.ADDRESS_EXACT,
                    candidate_parcel_id=c.parcel_id,
                    detail={"street": normalized.street},
                )
                for c in found
            ],
            disclosure=(
                "Multiple parcels share this situs address (condominium/stacked "
                "parcels); unit-level identification required (SRS REQ-RES-05)"
            ),
        )

    def _resolve_geometry(self, req: IntakeRequest) -> ResolutionDecision:
        geom = parse_wkt(req.geometry_wkt)
        if geom.geom_type == "Point":
            return self._resolve_point(geom)

        found = self._source.intersecting(req.geometry_wkt)
        if not found:
            return ResolutionDecision(
                status=ResolutionStatus.UNRESOLVED,
                disclosure="No parcel intersects the submitted geometry.",
            )

        scored = []
        for cand in found:
            score = iou(geom, parse_wkt(cand.geometry_wkt)) if cand.geometry_wkt else 0.0
            evidence = Evidence(
                kind=EvidenceKind.GEOMETRY_MATCH,
                candidate_parcel_id=cand.parcel_id,
                detail={"iou": round(score, 4)},
            )
            scored.append((score, cand, evidence))

        strong = [item for item in scored if item[0] >= _GEOMETRY_IOU_THRESHOLD]
        if len(strong) == 1:
            _, cand, ev = strong[0]
            return ResolutionDecision(
                status=ResolutionStatus.RESOLVED,
                parcel_id=cand.parcel_id,
                confidence=ConfidenceClass.STRONG,
                candidates=[cand],
                evidence=[ev],
            )

        # Ranking is for customer display only — the decision is theirs.
        scored.sort(key=lambda item: item[0], reverse=True)
        return ResolutionDecision(
            status=ResolutionStatus.AWAITING_CUSTOMER_INPUT,
            candidates=[cand for _, cand, _ in scored],
            evidence=[ev for _, _, ev in scored],
            disclosure=(
                "Submitted geometry intersects multiple parcels or matches none "
                "unambiguously; confirm the parcel."
            ),
        )

    def _resolve_point(self, geom) -> ResolutionDecision:
        found = self._source.containing_point(geom.x, geom.y)
        if not found:
            return ResolutionDecision(
                status=ResolutionStatus.UNRESOLVED,
                disclosure="Point location falls outside every known parcel.",
            )
        return ResolutionDecision(
            status=ResolutionStatus.AWAITING_CUSTOMER_INPUT,
            confidence=ConfidenceClass.SUPPORTING,
            candidates=found,
            evidence=[
                Evidence(
                    kind=EvidenceKind.POINT_IN_POLYGON,
                    candidate_parcel_id=c.parcel_id,
                    detail={"x": geom.x, "y": geom.y},
                )
                for c in found
            ],
            disclosure=(
                "A point location is supporting evidence, not parcel identity "
                "(SRS REQ-RES-02); confirm the parcel."
            ),
        )

    def confirm(
        self, decision: ResolutionDecision, selected_parcel_id: str
    ) -> ResolutionDecision:
        if decision.status != ResolutionStatus.AWAITING_CUSTOMER_INPUT:
            raise ValueError(
                f"confirm() requires status {ResolutionStatus.AWAITING_CUSTOMER_INPUT}, "
                f"got {decision.status}"
            )
        selected = [c for c in decision.candidates if c.parcel_id == selected_parcel_id]
        if not selected:
            raise ValueError(
                f"{selected_parcel_id!r} is not among the offered candidates"
            )
        cand = selected[0]
        prior = [e for e in decision.evidence if e.candidate_parcel_id == cand.parcel_id]
        if not prior:
            raise ValueError(
                "candidate has no supporting evidence; cannot confirm"
            )
        strongest = min(prior, key=lambda e: _KIND_RANK[e.kind]).kind
        evidence = list(decision.evidence) + [
            Evidence(
                kind=strongest,
                candidate_parcel_id=cand.parcel_id,
                detail={"customer_confirmed": True},
            )
        ]
        return ResolutionDecision(
            status=ResolutionStatus.RESOLVED,
            parcel_id=cand.parcel_id,
            confidence=ConfidenceClass.IDENTITY,
            candidates=decision.candidates,
            evidence=evidence,
            customer_selection=cand.parcel_id,
            disclosure=decision.disclosure,
        )
