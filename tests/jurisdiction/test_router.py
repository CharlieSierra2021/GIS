from pathlib import Path

import pytest
from shapely.geometry import box

from connectors.registry import load_registry
from jurisdiction import (
    AuthorityBoundary,
    JurisdictionRouter,
    RoutingStatus,
)

COUNTY = box(0, 0, 100, 100)
DELAND = box(10, 10, 30, 30)
DELTONA = box(40, 10, 60, 30)


@pytest.fixture(scope="module")
def router() -> JurisdictionRouter:
    return JurisdictionRouter(
        registry=load_registry(),
        county_boundary=COUNTY,
        municipal_boundaries=[
            AuthorityBoundary("deland", DELAND),
            AuthorityBoundary("deltona", DELTONA),
        ],
    )


def test_parcel_inside_municipality_resolves(router: JurisdictionRouter) -> None:
    result = router.route(box(15, 15, 20, 20))
    assert result.status == RoutingStatus.RESOLVED
    assert result.authority_id == "deland"
    assert result.evidence["overlap_fractions"]["deland"] == 1.0


def test_parcel_outside_municipalities_resolves_county(
    router: JurisdictionRouter,
) -> None:
    result = router.route(box(70, 70, 80, 80))
    assert result.status == RoutingStatus.RESOLVED
    assert result.authority_id == "volusia_uninc"


def test_parcel_straddling_boundary_is_ambiguous(router: JurisdictionRouter) -> None:
    result = router.route(box(25, 15, 35, 20))
    assert result.status == RoutingStatus.AMBIGUOUS
    assert result.authority_id is None
    assert result.candidates[0] == "deland"
    assert "volusia_uninc" in result.candidates
    assert "REQ-JUR-03" in result.disclosure


def test_parcel_overlapping_two_municipalities_is_ambiguous(
    router: JurisdictionRouter,
) -> None:
    result = router.route(box(20, 15, 50, 20))
    assert result.status == RoutingStatus.AMBIGUOUS
    assert "deland" in result.candidates
    assert "deltona" in result.candidates


def test_sliver_overlap_is_noise(router: JurisdictionRouter) -> None:
    # 0.2% inside deland — below tolerance, treated as unincorporated.
    result = router.route(box(29.99, 15, 35, 20))
    assert result.status == RoutingStatus.RESOLVED
    assert result.authority_id == "volusia_uninc"


def test_near_total_overlap_resolves_municipality(router: JurisdictionRouter) -> None:
    result = router.route(box(10, 10, 29.995, 30))
    assert result.status == RoutingStatus.RESOLVED
    assert result.authority_id == "deland"


def test_parcel_partly_outside_county_is_unresolved(router: JurisdictionRouter) -> None:
    result = router.route(box(95, 95, 105, 105))
    assert result.status == RoutingStatus.UNRESOLVED
    assert result.authority_id is None
    assert "not within Volusia County" in result.disclosure


def test_empty_parcel_raises(router: JurisdictionRouter) -> None:
    with pytest.raises(ValueError):
        router.route(box(0, 0, 0, 0).buffer(0).intersection(box(200, 200, 201, 201)))


def test_router_rejects_unknown_authority() -> None:
    with pytest.raises(ValueError):
        JurisdictionRouter(
            registry=load_registry(),
            county_boundary=COUNTY,
            municipal_boundaries=[AuthorityBoundary("narnia", DELAND)],
        )


def test_router_rejects_county_as_municipal_boundary() -> None:
    with pytest.raises(ValueError):
        JurisdictionRouter(
            registry=load_registry(),
            county_boundary=COUNTY,
            municipal_boundaries=[AuthorityBoundary("volusia_uninc", COUNTY)],
        )


def test_no_point_or_name_based_routing() -> None:
    assert not hasattr(JurisdictionRouter, "route_point")
    source = (Path(__file__).resolve().parents[2] / "src" / "jurisdiction" / "router.py").read_text(
        encoding="utf-8"
    )
    assert "postal" not in source
    assert "city_name" not in source
