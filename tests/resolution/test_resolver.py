from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from resolution.intake import IntakeKind, IntakeRequest
from resolution.models import ParcelCandidate, ResolutionDecision, ResolutionStatus
from resolution.resolver import ParcelResolver

VALIDATION_SET = Path(__file__).with_name("validation_set.yaml")


def _load_cases():
    data = yaml.safe_load(VALIDATION_SET.read_text(encoding="utf-8"))
    return data["cases"]


CASES = _load_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_validation_case(case: dict, resolver: ParcelResolver) -> None:
    decision = resolver.resolve(IntakeRequest(**case["intake"]))
    expected = case["expected"]
    assert decision.status.value == expected["status"], case["note"]
    assert decision.parcel_id == expected["parcel_id"], case["note"]
    expected_conf = expected["confidence"]
    assert (decision.confidence.value if decision.confidence else None) == expected_conf, (
        case["note"]
    )


def test_confirm_resumes_awaiting_decision(resolver: ParcelResolver) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
    )
    assert decision.status == ResolutionStatus.AWAITING_CUSTOMER_INPUT
    confirmed = resolver.confirm(decision, "C-101")
    assert confirmed.status == ResolutionStatus.RESOLVED
    assert confirmed.parcel_id == "C-101"
    assert confirmed.customer_selection == "C-101"
    assert any(
        e.detail.get("customer_confirmed") and e.candidate_parcel_id == "C-101"
        for e in confirmed.evidence
    )


def test_confirm_on_resolved_raises(resolver: ParcelResolver) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.PARCEL_ID, parcel_id="P-001")
    )
    assert decision.status == ResolutionStatus.RESOLVED
    with pytest.raises(ValueError):
        resolver.confirm(decision, "P-001")


def test_confirm_with_unknown_candidate_raises(resolver: ParcelResolver) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
    )
    with pytest.raises(ValueError):
        resolver.confirm(decision, "P-001")


def test_single_candidate_unit_mismatch_awaits(resolver: ParcelResolver) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="700 Canal Ct", unit="2")
    )
    assert decision.status == ResolutionStatus.AWAITING_CUSTOMER_INPUT
    assert "does not match" in decision.disclosure
    assert {c.parcel_id for c in decision.candidates} == {"U-1"}


def test_single_family_requested_unit_is_audited(resolver: ParcelResolver) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St", unit="9")
    )
    assert decision.status == ResolutionStatus.RESOLVED
    assert decision.parcel_id == "P-001"
    assert decision.evidence[0].detail["requested_unit_ignored"] == "9"


def test_confirm_candidate_without_evidence_raises(resolver: ParcelResolver) -> None:
    orphan = ParcelCandidate(parcel_id="GHOST", situs_address="1 NOWHERE ST")
    decision = ResolutionDecision(
        status=ResolutionStatus.AWAITING_CUSTOMER_INPUT,
        candidates=[orphan],
        evidence=[],
    )
    with pytest.raises(ValueError, match="no supporting evidence"):
        resolver.confirm(decision, "GHOST")


def test_resolver_has_no_silent_tiebreak() -> None:
    source = (Path(__file__).resolve().parents[2] / "src" / "resolution" / "resolver.py").read_text(
        encoding="utf-8"
    )
    for banned in (".area", "nearest", "largest"):
        assert banned not in source


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": IntakeKind.ADDRESS, "parcel_id": "P-001"},
        {"kind": IntakeKind.PARCEL_ID, "address": "123 Main St"},
        {"kind": IntakeKind.GEOMETRY, "parcel_id": "P-001"},
        {"kind": IntakeKind.ADDRESS},
    ],
)
def test_intake_requires_field_for_kind(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        IntakeRequest(**kwargs)
