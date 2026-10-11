from datetime import UTC, datetime

import pytest

from analysis.engine import ScreeningContext, screen
from analysis.findings import FindingStatus
from analysis.profile import load_profile
from connectors.registry import load_registry
from tests.analysis.conftest import PARCEL_WKT, StubFetcher, full_pages, page

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _registry():
    reg = load_registry().model_copy(deep=True)
    for ds_id in (
        "permits",
        "utility_service",
        "county_flu",
        "mun_flu",
        "sinkhole_reports",
        "fdep_contam",
        "fdot_roads",
    ):
        reg.dataset(ds_id).permissions.query = True
    return reg


def _ctx(registry):
    return ScreeningContext(
        job_id="job-acc",
        parcel_id="P-001",
        parcel_wkt=PARCEL_WKT,
        registry=registry,
        authority_id="volusia_uninc",
        now=NOW,
    )


@pytest.mark.acceptance
def test_fl_tst_06_flood_finding_zone_and_provenance() -> None:
    result = screen(_ctx(_registry()), load_profile(), StubFetcher(full_pages()))
    flood = next(f for f in result.findings if f.area == "flood")
    assert flood.status == FindingStatus.PRESENT
    assert "AE" in flood.evidence["zones"]
    assert "T" in flood.evidence["sfha_flags"]
    for field in ("observation_date", "publication_date", "retrieved_at"):
        assert field in flood.citation.model_fields_set
    # Stub provided no source dates: they stay None, never fabricated.
    assert flood.citation.observation_date is None
    assert flood.citation.publication_date is None


@pytest.mark.acceptance
def test_fl_tst_07_empty_nwi_is_no_record_not_absence() -> None:
    pages = full_pages()
    pages["nwi_wetlands"] = page()
    result = screen(_ctx(_registry()), load_profile(), StubFetcher(pages))
    wetlands = next(f for f in result.findings if f.area == "wetlands")
    assert wetlands.status == FindingStatus.NOT_FOUND
    assert "No wetland record found" in wetlands.statement
    assert "no wetlands" not in wetlands.statement.lower()
