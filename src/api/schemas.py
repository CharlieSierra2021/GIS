"""Request/response schemas for the jobs API."""

from typing import Literal

from pydantic import BaseModel, model_validator

from resolution.intake import IntakeKind, IntakeRequest


class JobCreate(BaseModel):
    kind: Literal["address", "parcel_id", "geometry"]
    address: str | None = None
    unit: str | None = None
    parcel_id: str | None = None
    geometry_wkt: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _empty_strings_to_none(cls, data):
        if isinstance(data, dict):
            return {k: (v if v != "" else None) for k, v in data.items()}
        return data

    def to_intake(self) -> IntakeRequest:
        return IntakeRequest(
            kind=IntakeKind(self.kind),
            address=self.address,
            unit=self.unit,
            parcel_id=self.parcel_id,
            geometry_wkt=self.geometry_wkt,
        )


class CandidateSelect(BaseModel):
    parcel_id: str


class ReviewDecision(BaseModel):
    reviewer: str
    approve: Literal["publish", "qualified", "reject"]
    rationale: str


def job_out(job) -> dict:
    out = job.model_dump(mode="json")
    if job.resolution and job.state.value == "awaiting_customer_input":
        out["candidates"] = [c.parcel_id for c in job.resolution.candidates]
    return out
