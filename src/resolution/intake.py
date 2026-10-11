"""Intake request model and address normalization (SRS REQ-RES)."""

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, model_validator


class IntakeKind(StrEnum):
    ADDRESS = "address"
    PARCEL_ID = "parcel_id"
    GEOMETRY = "geometry"


class IntakeRequest(BaseModel):
    kind: IntakeKind
    address: str | None = None
    unit: str | None = None
    parcel_id: str | None = None
    geometry_wkt: str | None = None

    @model_validator(mode="after")
    def _field_for_kind_present(self) -> "IntakeRequest":
        required = {
            IntakeKind.ADDRESS: "address",
            IntakeKind.PARCEL_ID: "parcel_id",
            IntakeKind.GEOMETRY: "geometry_wkt",
        }[self.kind]
        if getattr(self, required) is None:
            raise ValueError(f"intake kind {self.kind!r} requires {required!r}")
        return self


_SUFFIXES = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "ROAD": "RD",
    "DRIVE": "DR",
    "BOULEVARD": "BLVD",
    "LANE": "LN",
    "COURT": "CT",
    "CIRCLE": "CIR",
}

_UNIT_RE = re.compile(r"(?:^|\s)(?:APT|UNIT|STE|#)\s*([A-Z0-9-]+)\s*$")


@dataclass(frozen=True)
class NormalizedAddress:
    street: str
    unit: str | None = None


def normalize_address(s: str) -> NormalizedAddress:
    """Uppercase, collapse whitespace, strip punctuation (except '#'),
    expand common street suffixes, and split a trailing unit designator."""
    text = s.upper()
    text = re.sub(r"[^\w\s#-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    unit = None
    m = _UNIT_RE.search(text)
    if m:
        unit = m.group(1)
        text = text[: m.start()].strip()

    text = " ".join(_SUFFIXES.get(tok, tok) for tok in text.split())
    return NormalizedAddress(street=text, unit=unit)
