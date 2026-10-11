"""Analysis profile loading — SRS REQ-ANL profiles are data, not code."""

from importlib import resources
from typing import get_args

import yaml
from pydantic import BaseModel

from analysis.findings import FindingArea


class AreaSpec(BaseModel):
    dataset: str
    analyzer: str
    mandatory: bool = False
    spatial_rel: str = "intersects"
    buffer_m: float | None = None
    label: str | None = None
    jurisdiction_dependent: bool = False


class Profile(BaseModel):
    profile: str
    version: str
    areas: dict[str, AreaSpec]


def load_profile(name: str = "florida_land_screening_v1") -> Profile:
    text = (
        resources.files("analysis")
        .joinpath("profiles", f"{name}.yaml")
        .read_text(encoding="utf-8")
    )
    profile = Profile.model_validate(yaml.safe_load(text))
    expected = set(get_args(FindingArea))
    if set(profile.areas) != expected:
        raise ValueError(
            f"profile {name!r} areas {sorted(profile.areas)} != the nine "
            f"finding areas {sorted(expected)}"
        )
    return profile
