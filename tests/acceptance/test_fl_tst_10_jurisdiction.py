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


@pytest.fixture(scope="module")
def router() -> JurisdictionRouter:
    return JurisdictionRouter(
        registry=load_registry(),
        county_boundary=COUNTY,
        municipal_boundaries=[AuthorityBoundary("deland", DELAND)],
    )


@pytest.mark.acceptance
def test_municipal_parcel_never_attributed_to_county(router: JurisdictionRouter) -> None:
    # Fully municipal parcel resolves to the municipality, not the county.
    resolved = router.route(box(15, 15, 20, 20))
    assert resolved.status == RoutingStatus.RESOLVED
    assert resolved.authority_id == "deland"

    # An ambiguous parcel never returns the county as authority_id.
    ambiguous = router.route(box(25, 15, 35, 20))
    assert ambiguous.status == RoutingStatus.AMBIGUOUS
    assert ambiguous.authority_id != "volusia_uninc"
    assert ambiguous.authority_id is None
