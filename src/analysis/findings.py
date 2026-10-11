"""Finding model — SRS REQ-ANL-03/05, ICD §10/§13.

Every finding carries a status, boundary-checked statement, evidence, and a
source citation with three independent dates. ``null`` dates are disclosed as
"unknown" downstream, never fabricated. ``NOT_FOUND`` means "no record found"
— absence of a record is never rendered as absence of a condition.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, model_validator

FindingArea = Literal[
    "flood",
    "wetlands",
    "hydric_soils",
    "subsidence",
    "permits",
    "contamination",
    "land_use",
    "access",
    "utilities",
]


class FindingStatus(StrEnum):
    PRESENT = "present"
    NOT_FOUND = "not_found"
    NOT_ASSESSED = "not_assessed"


# ICD §10 / SRS REQ-ANL-04: phrases a finding may never state or imply.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "no wetlands",
    "not in a flood zone",
    "no flood risk",
    "site is clean",
    "no contamination",
    "flood determination",
    "certified",
    "delineat",
    "buildable",
    "zoning permits",
    "survey",
)


def check_boundary_language(text: str) -> list[str]:
    """Return the forbidden phrases present in ``text`` (case-insensitive)."""
    lowered = text.lower()
    return [p for p in FORBIDDEN_PHRASES if p in lowered]


class SourceCitation(BaseModel):
    dataset_id: str
    provider_id: str
    feature_keys: list[str] = []
    observation_date: str | None = None
    publication_date: str | None = None
    retrieved_at: datetime | None = None
    registry_version: str
    license_name: str | None = None
    license_gate: str | None = None


class Finding(BaseModel):
    id: str
    area: FindingArea
    status: FindingStatus
    statement: str
    evidence: dict = {}
    citation: SourceCitation | None = None
    disclosure: str | None = None
    mandatory: bool

    @model_validator(mode="after")
    def _check(self) -> "Finding":
        hits = check_boundary_language(self.statement)
        if hits:
            raise ValueError(
                f"statement violates ICD §10 boundary language: {hits}"
            )
        if self.status == FindingStatus.NOT_ASSESSED and not self.disclosure:
            raise ValueError("NOT_ASSESSED findings must carry a disclosure")
        if self.status == FindingStatus.PRESENT and (
            not self.citation or not self.citation.feature_keys
        ):
            raise ValueError("PRESENT findings require a citation with feature keys")
        return self


# Singular record labels so "No <label> record found" never reads as a
# negative claim about the world (ICD §10 right column).
_AREA_RECORD_LABEL = {
    "flood": "flood",
    "wetlands": "wetland",
    "hydric_soils": "hydric soil",
    "subsidence": "subsidence",
    "permits": "permit",
    "contamination": "contamination",
    "land_use": "land use",
    "access": "access",
    "utilities": "utility",
}


def not_found(
    id: str,
    area: FindingArea,
    *,
    dataset_id: str,
    provider_id: str,
    registry_version: str,
    retrieved_at: datetime | None,
    mandatory: bool,
    observation_date: str | None = None,
    publication_date: str | None = None,
    license_name: str | None = None,
    license_gate: str | None = None,
) -> Finding:
    date = retrieved_at.date().isoformat() if retrieved_at else "unknown"
    label = _AREA_RECORD_LABEL[area]
    return Finding(
        id=id,
        area=area,
        status=FindingStatus.NOT_FOUND,
        statement=(
            f"No {label} record found in {dataset_id} as retrieved {date}; "
            f"absence of a record is not evidence of absence."
        ),
        citation=SourceCitation(
            dataset_id=dataset_id,
            provider_id=provider_id,
            observation_date=observation_date,
            publication_date=publication_date,
            retrieved_at=retrieved_at,
            registry_version=registry_version,
            license_name=license_name,
            license_gate=license_gate,
        ),
        disclosure="No matching record returned by the source.",
        mandatory=mandatory,
    )


def not_assessed(
    id: str,
    area: FindingArea,
    reason: str,
    *,
    mandatory: bool,
    dataset_id: str | None = None,
) -> Finding:
    return Finding(
        id=id,
        area=area,
        status=FindingStatus.NOT_ASSESSED,
        statement=f"{area.replace('_', ' ')} was not assessed.",
        disclosure=f"Not assessed — {reason}",
        evidence={"dataset_id": dataset_id} if dataset_id else {},
        mandatory=mandatory,
    )


class ScreeningResult(BaseModel):
    job_id: str
    parcel_id: str
    profile: str
    profile_version: str
    registry_version: str
    findings: list[Finding] = []
    produced_at: datetime
