"""Report manifest — SRS REQ-RPT-03/04, ICD §13.

The manifest is the auditable record of what a report contains: every cited
dataset's licence status, vintage, imagery licensing mode, exclusions, and
the rendered-HTML hash.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from quality.gates import Disposition, GateResult

# SRS §1.3 product boundary, in prose form. It legitimately contains words
# the finding-statement guard forbids ("survey", "flood determination") —
# the boundary check applies to Finding.statement, never to this statement.
BOUNDARY_STATEMENT = (
    "This is an automated due-diligence screening report. It is not a land "
    "survey or certified boundary, not a lending-compliant flood "
    "determination, not a wetland delineation or environmental assessment, "
    "and not a zoning or buildability determination. Findings are screening "
    "indicators with cited provenance; an absent record is not evidence of "
    "absence."
)


class LicenseDisclosure(BaseModel):
    dataset_id: str
    provider_name: str | None = None
    license_name: str | None = None
    gate: str | None = None
    display_allowed: bool
    report_allowed: bool
    vintage_observation: str | None = None
    vintage_publication: str | None = None
    retrieved_at: datetime | None = None


class ReportManifest(BaseModel):
    job_id: str
    account_id: str
    parcel_id: str | None
    generated_at: datetime
    registry_version: str
    profile: str
    profile_version: str
    template_version: str
    disposition: Disposition
    qualifications: list[str] = []
    gate_results: list[GateResult] = []
    disclosures: list[LicenseDisclosure] = []
    imagery: Literal["licensed", "denied"]
    map_layers: list[str] = []
    excluded_content: list[str] = []
    boundary_statement: str
    pdf: dict = {}
    html_sha256: str
