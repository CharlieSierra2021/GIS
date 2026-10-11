from analysis.engine import ScreeningContext, screen
from analysis.findings import FindingStatus, check_boundary_language
from analysis.profile import load_profile
from connectors.contract import ConnectorError, FailureClass
from connectors.registry import load_registry
from tests.analysis.conftest import (
    NOW,
    PARCEL_WKT,
    StubFetcher,
    feat,
    full_pages,
    page,
)


def _ctx(registry, authority_id="volusia_uninc", job_id="job-1"):
    return ScreeningContext(
        job_id=job_id,
        parcel_id="P-001",
        parcel_wkt=PARCEL_WKT,
        registry=registry,
        authority_id=authority_id,
        now=NOW,
    )


def _by_area(result, area):
    return next(f for f in result.findings if f.area == area)


def test_full_run_all_present(granted_registry) -> None:
    result = screen(_ctx(granted_registry), load_profile(), StubFetcher(full_pages()))
    assert len(result.findings) == 9
    for f in result.findings:
        assert f.status == FindingStatus.PRESENT
        assert check_boundary_language(f.statement) == []
        assert f.citation.registry_version == "0.1.0"
        assert f.citation.retrieved_at is not None
        assert f.id == f"job-1:{f.area}"
    assert "AE" in _by_area(result, "flood").statement


def test_empty_page_is_not_found(granted_registry) -> None:
    pages = full_pages()
    pages["nfhl_flood"] = page()
    result = screen(_ctx(granted_registry), load_profile(), StubFetcher(pages))
    flood = _by_area(result, "flood")
    assert flood.status == FindingStatus.NOT_FOUND
    assert "not evidence of absence" in flood.statement


def test_connector_error_is_not_assessed(granted_registry) -> None:
    pages = full_pages()
    pages["nfhl_flood"] = ConnectorError(
        FailureClass.SOURCE_UNAVAILABLE, detail="HTTP 503"
    )
    result = screen(_ctx(granted_registry), load_profile(), StubFetcher(pages))
    flood = _by_area(result, "flood")
    assert flood.status == FindingStatus.NOT_ASSESSED
    assert "source_unavailable" in flood.disclosure
    assert _by_area(result, "wetlands").status == FindingStatus.PRESENT


def test_null_query_right_denies_before_fetch() -> None:
    # Real registry: permits.query is null -> NOT_ASSESSED, fetch never called.
    reg = load_registry().model_copy(deep=True)
    for ds_id in (
        "utility_service",
        "county_flu",
        "mun_flu",
        "sinkhole_reports",
        "fdep_contam",
        "fdot_roads",
    ):
        reg.dataset(ds_id).permissions.query = True
    fetcher = StubFetcher(full_pages())
    result = screen(_ctx(reg), load_profile(), fetcher)
    permits = _by_area(result, "permits")
    assert permits.status == FindingStatus.NOT_ASSESSED
    assert "registry denies query for permits" in permits.disclosure
    assert not fetcher.called("permits")


def test_unresolved_authority_withholds_land_use(granted_registry) -> None:
    fetcher = StubFetcher(full_pages())
    result = screen(_ctx(granted_registry, authority_id=None), load_profile(), fetcher)
    land_use = _by_area(result, "land_use")
    assert land_use.status == FindingStatus.NOT_ASSESSED
    assert "REQ-JUR-03" in land_use.disclosure
    assert not fetcher.called("county_flu")
    assert not fetcher.called("mun_flu")


def test_municipal_authority_uses_mun_flu(granted_registry) -> None:
    fetcher = StubFetcher(full_pages())
    result = screen(_ctx(granted_registry, authority_id="deland"), load_profile(), fetcher)
    land_use = _by_area(result, "land_use")
    assert land_use.status == FindingStatus.PRESENT
    assert "City of DeLand" in land_use.statement
    assert fetcher.called("mun_flu")
    assert fetcher.authority_for("mun_flu") == "deland"
    assert not fetcher.called("county_flu")
    assert land_use.citation.dataset_id == "mun_flu"


def test_county_authority_uses_county_flu(granted_registry) -> None:
    fetcher = StubFetcher(full_pages())
    result = screen(
        _ctx(granted_registry, authority_id="volusia_uninc"),
        load_profile(),
        fetcher,
    )
    assert _by_area(result, "land_use").status == FindingStatus.PRESENT
    assert fetcher.called("county_flu")
    assert fetcher.authority_for("county_flu") == "volusia_uninc"
    assert not fetcher.called("mun_flu")


def test_mun_flu_failure_discloses_authority(granted_registry) -> None:
    pages = full_pages()
    pages["mun_flu"] = ConnectorError(
        FailureClass.SOURCE_UNAVAILABLE, detail="down"
    )
    result = screen(_ctx(granted_registry, authority_id="deland"), load_profile(), StubFetcher(pages))
    land_use = _by_area(result, "land_use")
    assert land_use.status == FindingStatus.NOT_ASSESSED
    assert "municipal FLU unavailable — authority: City of DeLand" in land_use.disclosure


def test_proximity_beyond_buffer_is_not_found(granted_registry) -> None:
    pages = full_pages()
    # ~50 km away — far outside the 1609 m subsidence buffer.
    pages["sinkhole_reports"] = page(
        feat("k1", {}, "POINT (-80.5 29.5)")
    )
    result = screen(_ctx(granted_registry), load_profile(), StubFetcher(pages))
    subs = _by_area(result, "subsidence")
    assert subs.status == FindingStatus.NOT_FOUND
    assert "not evidence of absence" in subs.statement


def test_proximity_nearest_distance(granted_registry) -> None:
    result = screen(_ctx(granted_registry), load_profile(), StubFetcher(full_pages()))
    subs = _by_area(result, "subsidence")
    # Fixture point ~1 km east of the parcel; approximate equirectangular.
    assert 800 < subs.evidence["nearest_m"] < 1200
