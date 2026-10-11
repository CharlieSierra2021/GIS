"""Parcel-resolution data model — SRS REQ-RES-01..06."""

from enum import StrEnum

from pydantic import BaseModel


class EvidenceKind(StrEnum):
    PARCEL_ID_EXACT = "parcel_id_exact"
    ADDRESS_EXACT = "address_exact"
    ADDRESS_FUZZY = "address_fuzzy"
    UNIT_EXACT = "unit_exact"
    GEOMETRY_MATCH = "geometry_match"
    POINT_IN_POLYGON = "point_in_polygon"


class Evidence(BaseModel):
    kind: EvidenceKind
    candidate_parcel_id: str
    detail: dict = {}


class ParcelCandidate(BaseModel):
    """One row from basemap_parcels / CAMA."""

    parcel_id: str
    situs_address: str | None = None
    unit: str | None = None
    geometry_wkt: str | None = None
    is_condo_unit: bool = False
    parent_parcel_id: str | None = None


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AWAITING_CUSTOMER_INPUT = "awaiting_customer_input"
    UNRESOLVED = "unresolved"


class ConfidenceClass(StrEnum):
    IDENTITY = "identity"
    STRONG = "strong"
    SUPPORTING = "supporting"


class ResolutionDecision(BaseModel):
    status: ResolutionStatus
    parcel_id: str | None = None
    confidence: ConfidenceClass | None = None
    candidates: list[ParcelCandidate] = []
    evidence: list[Evidence] = []
    customer_selection: str | None = None
    disclosure: str | None = None
