from datetime import UTC, datetime, timedelta

import pytest

from analysis.findings import (
    Finding,
    FindingStatus,
    ScreeningResult,
    SourceCitation,
    not_assessed,
    not_found,
)
from connectors.registry import load_registry
from quality.gates import (
    Disposition,
    GateInputs,
    GateOutcome,
    apply_review,
    evaluate,
)
from resolution.models import (
    ConfidenceClass,
    ResolutionDecision,
    ResolutionStatus,
)

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _registry(**perm_overrides):
    """Real registry with per-dataset permission tweaks:
    perm_overrides={"nfhl_flood": {"report": True}}"""
    reg = load_registry().model_copy(deep=True)
    for ds_id, perms in perm_overrides.items():
        for k, v in perms.items():
            setattr(reg.dataset(ds_id).permissions, k, v)
    return reg


def _resolved(confidence=ConfidenceClass.IDENTITY) -> ResolutionDecision:
    return ResolutionDecision(
        status=ResolutionStatus.RESOLVED,
        parcel_id="P-001",
        confidence=confidence,
    )


def _screening(findings) -> ScreeningResult:
    return ScreeningResult(
        job_id="job-1",
        parcel_id="P-001",
        profile="florida_land_screening_v1",
        profile_version="1.0",
        registry_version="0.1.0",
        findings=findings,
        produced_at=NOW,
    )


def _present_finding(
    dataset_id="nfhl_flood",
    provider_id="fema_nfhl",
    retrieved_at=None,
    mandatory=True,
    geometry=False,
) -> Finding:
    return Finding(
        id=f"f-{dataset_id}",
        area="flood",
        status=FindingStatus.PRESENT,
        statement=(
            "Parcel intersects FEMA zone AE per NFHL panel 12127C0340H "
            "effective 2018-02-02."
        ),
        evidence={"geometry_wkt": "POINT(-81 29)"} if geometry else {},
        citation=SourceCitation(
            dataset_id=dataset_id,
            provider_id=provider_id,
            feature_keys=["101"],
            retrieved_at=retrieved_at or NOW,
            registry_version="0.1.0",
            license_name="FEMA NFHL terms",
            license_gate="L3",
        ),
        mandatory=mandatory,
    )


def _inputs(findings, **kwargs) -> GateInputs:
    return GateInputs(
        resolution=kwargs.get("resolution", _resolved()),
        screening=_screening(findings),
        registry=kwargs.get("registry", _registry()),
        now=NOW,
        conflicts=kwargs.get("conflicts", []),
    )


def test_auto_publish_when_all_pass() -> None:
    reg = _registry(nfhl_flood={"report": True})
    decision = evaluate(_inputs([_present_finding()], registry=reg))
    assert decision.disposition == Disposition.AUTO_PUBLISH
    assert [g.outcome for g in decision.gates] == [GateOutcome.PASS] * 5


def test_identity_blocked_but_all_gates_recorded() -> None:
    reg = _registry(nfhl_flood={"report": True})
    awaiting = ResolutionDecision(status=ResolutionStatus.AWAITING_CUSTOMER_INPUT)
    decision = evaluate(
        _inputs([_present_finding()], registry=reg, resolution=awaiting)
    )
    assert decision.disposition == Disposition.BLOCKED
    assert len(decision.gates) == 5
    assert decision.gates[0].outcome == GateOutcome.BLOCKED
    assert decision.gates[4].outcome == GateOutcome.PASS


def test_license_blocks_on_null_report() -> None:
    finding = _present_finding(dataset_id="ortho_2024", provider_id="volusia_county_gis")
    decision = evaluate(_inputs([finding]))
    assert decision.disposition == Disposition.BLOCKED
    gate = next(g for g in decision.gates if g.gate == "license")
    assert gate.outcome == GateOutcome.BLOCKED
    assert any("ortho_2024" in r and "report" in r for r in gate.reasons)


def test_license_blocks_display_for_geometry_evidence() -> None:
    reg = _registry(nfhl_flood={"report": True, "display": None})
    decision = evaluate(
        _inputs([_present_finding(geometry=True)], registry=reg)
    )
    assert decision.disposition == Disposition.BLOCKED
    gate = next(g for g in decision.gates if g.gate == "license")
    assert any("display" in r for r in gate.reasons)


def test_mandatory_stale_goes_to_review() -> None:
    reg = _registry(nfhl_flood={"report": True})
    old = NOW - timedelta(days=400)
    decision = evaluate(
        _inputs([_present_finding(retrieved_at=old, mandatory=True)], registry=reg)
    )
    assert decision.disposition == Disposition.HUMAN_REVIEW
    gate = next(g for g in decision.gates if g.gate == "freshness")
    assert gate.outcome == GateOutcome.REVIEW


def test_nonmandatory_stale_is_qualified() -> None:
    reg = _registry(nfhl_flood={"report": True})
    old = NOW - timedelta(days=400)
    decision = evaluate(
        _inputs([_present_finding(retrieved_at=old, mandatory=False)], registry=reg)
    )
    assert decision.disposition == Disposition.QUALIFIED_OUTPUT
    assert decision.qualifications


def test_mandatory_not_assessed_goes_to_review() -> None:
    finding = not_assessed(
        "f-flood", "flood", "source_unavailable", mandatory=True
    )
    decision = evaluate(_inputs([finding]))
    assert decision.disposition == Disposition.HUMAN_REVIEW


def test_not_found_only_is_qualified_never_auto() -> None:
    finding = not_found(
        "f-nwi",
        "wetlands",
        dataset_id="nwi_wetlands",
        provider_id="usfws_nwi",
        registry_version="0.1.0",
        retrieved_at=NOW,
        mandatory=True,
    )
    # nwi report is null in the real registry -> license blocks; grant it
    reg = _registry(nwi_wetlands={"report": True})
    decision = evaluate(_inputs([finding], registry=reg))
    assert decision.disposition == Disposition.QUALIFIED_OUTPUT


def test_material_conflict_goes_to_review() -> None:
    reg = _registry(nfhl_flood={"report": True})
    decision = evaluate(
        _inputs(
            [_present_finding()],
            registry=reg,
            conflicts=["material: parcel geometry differs between CAMA and basemap"],
        )
    )
    assert decision.disposition == Disposition.HUMAN_REVIEW


def test_apply_review_paths() -> None:
    reg = _registry(nfhl_flood={"report": True})
    base = evaluate(
        _inputs(
            [_present_finding()],
            registry=reg,
            conflicts=["material: boundary disagreement"],
        )
    )
    assert base.disposition == Disposition.HUMAN_REVIEW

    pub = apply_review(
        base.model_copy(deep=True), "rev-1", "publish", "verified ok"
    )
    assert pub.disposition == Disposition.AUTO_PUBLISH
    assert pub.review["reviewer"] == "rev-1"
    assert pub.review["rationale"] == "verified ok"

    qual = apply_review(
        base.model_copy(deep=True), "rev-1", "qualified", "disclose it"
    )
    assert qual.disposition == Disposition.QUALIFIED_OUTPUT

    rej = apply_review(base.model_copy(deep=True), "rev-1", "reject", "bad data")
    assert rej.disposition == Disposition.BLOCKED


def test_apply_review_cannot_override_blocked() -> None:
    decision = evaluate(_inputs([_present_finding(dataset_id="ortho_2024")]))
    assert decision.disposition == Disposition.BLOCKED
    with pytest.raises(ValueError):
        apply_review(decision, "rev-1", "publish", "try anyway")


def test_apply_review_rejects_auto_publish() -> None:
    reg = _registry(nfhl_flood={"report": True})
    decision = evaluate(_inputs([_present_finding()], registry=reg))
    assert decision.disposition == Disposition.AUTO_PUBLISH
    with pytest.raises(ValueError):
        apply_review(decision, "rev-1", "qualified", "no review needed")
