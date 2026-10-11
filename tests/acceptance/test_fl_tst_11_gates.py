from datetime import UTC, datetime, timedelta

import pytest

from analysis.findings import (
    Finding,
    FindingStatus,
    ScreeningResult,
    SourceCitation,
    not_found,
)
from connectors.registry import load_registry
from quality.gates import Disposition, GateInputs, evaluate
from resolution.models import (
    ConfidenceClass,
    ResolutionDecision,
    ResolutionStatus,
)

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _registry(**perm_overrides):
    reg = load_registry().model_copy(deep=True)
    for ds_id, perms in perm_overrides.items():
        for k, v in perms.items():
            setattr(reg.dataset(ds_id).permissions, k, v)
    return reg


def _screening(findings) -> ScreeningResult:
    return ScreeningResult(
        job_id="job-acc",
        parcel_id="P-001",
        profile="florida_land_screening_v1",
        profile_version="1.0",
        registry_version="0.1.0",
        findings=findings,
        produced_at=NOW,
    )


def _nfhl_finding(retrieved_at=None, geometry=False) -> Finding:
    return Finding(
        id="f-flood",
        area="flood",
        status=FindingStatus.PRESENT,
        statement=(
            "Parcel intersects FEMA zone AE per NFHL panel 12127C0340H "
            "effective 2018-02-02."
        ),
        evidence={"geometry_wkt": "POINT(-81 29)"} if geometry else {},
        citation=SourceCitation(
            dataset_id="nfhl_flood",
            provider_id="fema_nfhl",
            feature_keys=["101"],
            retrieved_at=retrieved_at or NOW,
            registry_version="0.1.0",
        ),
        mandatory=True,
    )


def _inputs(findings, registry, conflicts=None) -> GateInputs:
    return GateInputs(
        resolution=ResolutionDecision(
            status=ResolutionStatus.RESOLVED,
            parcel_id="P-001",
            confidence=ConfidenceClass.IDENTITY,
        ),
        screening=_screening(findings),
        registry=registry,
        now=NOW,
        conflicts=conflicts or [],
    )


@pytest.mark.acceptance
def test_fl_tst_11_all_four_dispositions() -> None:
    reg = _registry(nfhl_flood={"report": True})

    auto = evaluate(_inputs([_nfhl_finding()], reg))
    assert auto.disposition == Disposition.AUTO_PUBLISH

    qualified = evaluate(
        _inputs(
            [
                not_found(
                    "f-nwi",
                    "wetlands",
                    dataset_id="nwi_wetlands",
                    provider_id="usfws_nwi",
                    registry_version="0.1.0",
                    retrieved_at=NOW,
                    mandatory=True,
                )
            ],
            _registry(nwi_wetlands={"report": True}),
        )
    )
    assert qualified.disposition == Disposition.QUALIFIED_OUTPUT

    review = evaluate(
        _inputs(
            [_nfhl_finding(retrieved_at=NOW - timedelta(days=400))],
            reg,
        )
    )
    assert review.disposition == Disposition.HUMAN_REVIEW

    blocked = evaluate(
        _inputs(
            [
                Finding(
                    id="f-ortho",
                    area="access",
                    status=FindingStatus.PRESENT,
                    statement="Ortho tile intersects the parcel extent.",
                    citation=SourceCitation(
                        dataset_id="ortho_2024",
                        provider_id="volusia_county_gis",
                        feature_keys=["t1"],
                        retrieved_at=NOW,
                        registry_version="0.1.0",
                    ),
                    mandatory=False,
                )
            ],
            reg,
        )
    )
    assert blocked.disposition == Disposition.BLOCKED


@pytest.mark.acceptance
def test_fl_tst_11_license_block_is_never_qualified() -> None:
    reg = _registry(nfhl_flood={"report": True})
    decision = evaluate(
        _inputs(
            [
                _nfhl_finding(),
                Finding(
                    id="f-ortho",
                    area="access",
                    status=FindingStatus.PRESENT,
                    statement="Ortho tile intersects the parcel extent.",
                    citation=SourceCitation(
                        dataset_id="ortho_2024",
                        provider_id="volusia_county_gis",
                        feature_keys=["t1"],
                        retrieved_at=NOW,
                        registry_version="0.1.0",
                    ),
                    mandatory=False,
                ),
            ],
            reg,
        )
    )
    # Every other gate passes, yet a null report right still blocks.
    assert decision.disposition == Disposition.BLOCKED
    assert decision.disposition != Disposition.QUALIFIED_OUTPUT
