from typing import get_args

from analysis.findings import FindingArea
from analysis.profile import load_profile


def test_profile_loads_with_nine_areas() -> None:
    profile = load_profile()
    assert profile.profile == "florida_land_screening_v1"
    assert profile.version == "1.0.0"
    assert len(profile.areas) == 9
    assert set(profile.areas) == set(get_args(FindingArea))


def test_profile_area_specs() -> None:
    profile = load_profile()
    assert profile.areas["flood"].dataset == "nfhl_flood"
    assert profile.areas["flood"].mandatory is True
    assert profile.areas["land_use"].jurisdiction_dependent is True
    assert profile.areas["contamination"].buffer_m == 402
