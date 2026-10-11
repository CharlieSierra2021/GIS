from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from analysis.findings import (
    Finding,
    FindingStatus,
    SourceCitation,
    check_boundary_language,
    not_assessed,
    not_found,
)


def test_not_found_forbidden_phrase_rejected() -> None:
    with pytest.raises(ValidationError):
        Finding(
            id="f1",
            area="wetlands",
            status=FindingStatus.NOT_FOUND,
            statement="There are no wetlands on this parcel.",
            citation=None,
            mandatory=True,
        )


def test_not_found_helper_is_valid() -> None:
    finding = not_found(
        "f1",
        "wetlands",
        dataset_id="nwi_wetlands",
        provider_id="usfws_nwi",
        registry_version="0.1.0",
        retrieved_at=datetime.now(UTC),
        mandatory=True,
    )
    assert "not evidence of absence" in finding.statement
    assert finding.status == FindingStatus.NOT_FOUND
    assert finding.citation.dataset_id == "nwi_wetlands"


def test_not_assessed_requires_disclosure() -> None:
    with pytest.raises(ValidationError):
        Finding(
            id="f1",
            area="flood",
            status=FindingStatus.NOT_ASSESSED,
            statement="Flood was not assessed.",
            mandatory=True,
        )
    ok = not_assessed("f1", "flood", "source_unavailable", mandatory=True)
    assert "Not assessed" in ok.disclosure


def test_present_requires_citation_with_keys() -> None:
    with pytest.raises(ValidationError):
        Finding(
            id="f1",
            area="flood",
            status=FindingStatus.PRESENT,
            statement="Parcel intersects FEMA zone AE per NFHL panel 12127C0340H.",
            citation=SourceCitation(
                dataset_id="nfhl_flood",
                provider_id="fema_nfhl",
                registry_version="0.1.0",
            ),
            mandatory=True,
        )


def test_boundary_language_case_insensitive() -> None:
    assert check_boundary_language("This is a Flood Determination") == [
        "flood determination"
    ]
    assert check_boundary_language(
        "Parcel intersects FEMA zone AE per NFHL panel 12127C0340H "
        "effective 2018-02-02"
    ) == []
