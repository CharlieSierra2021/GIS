import pytest
from shapely.geometry import box

from resolution.fixtures import InMemoryParcelSource
from resolution.intake import IntakeKind, IntakeRequest
from resolution.models import ParcelCandidate, ResolutionStatus
from resolution.resolver import ParcelResolver

CONDO_WKT = box(40, 0, 50, 10).wkt


@pytest.fixture(scope="module")
def resolver() -> ParcelResolver:
    return ParcelResolver(
        InMemoryParcelSource(
            [
                ParcelCandidate(
                    parcel_id="P-001",
                    situs_address="123 MAIN ST",
                    geometry_wkt=box(0, 0, 10, 10).wkt,
                ),
                ParcelCandidate(
                    parcel_id="C-000",
                    situs_address="500 OCEAN BLVD",
                    geometry_wkt=CONDO_WKT,
                ),
                ParcelCandidate(
                    parcel_id="C-101",
                    situs_address="500 OCEAN BLVD",
                    unit="101",
                    geometry_wkt=CONDO_WKT,
                    is_condo_unit=True,
                    parent_parcel_id="C-000",
                ),
                ParcelCandidate(
                    parcel_id="C-102",
                    situs_address="500 OCEAN BLVD",
                    unit="102",
                    geometry_wkt=CONDO_WKT,
                    is_condo_unit=True,
                    parent_parcel_id="C-000",
                ),
            ]
        )
    )


@pytest.mark.acceptance
def test_fl_tst_02_address_resolves_to_parcel(resolver: ParcelResolver) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    assert decision.status == ResolutionStatus.RESOLVED
    assert decision.parcel_id == "P-001"


@pytest.mark.acceptance
def test_fl_tst_03_ambiguous_awaits_customer_then_resumes(
    resolver: ParcelResolver,
) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
    )
    assert decision.status == ResolutionStatus.AWAITING_CUSTOMER_INPUT
    assert decision.parcel_id is None  # no candidate auto-chosen

    resumed = resolver.confirm(decision, "C-102")
    assert resumed.status == ResolutionStatus.RESOLVED
    assert resumed.customer_selection == "C-102"


@pytest.mark.acceptance
def test_fl_tst_04_condo_unit_level_match(resolver: ParcelResolver) -> None:
    decision = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd", unit="101")
    )
    assert decision.status == ResolutionStatus.RESOLVED
    assert decision.parcel_id == "C-101"
    # The building parcel is never returned when unit candidates exist.
    assert decision.parcel_id != "C-000"

    no_unit = resolver.resolve(
        IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
    )
    assert no_unit.parcel_id != "C-000"
    assert "C-000" in {c.parcel_id for c in no_unit.candidates}
