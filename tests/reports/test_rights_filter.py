from datetime import UTC, datetime

from analysis.findings import Finding, FindingStatus, SourceCitation
from connectors.registry import load_registry
from reports.publisher import RightsFilter

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _finding(dataset_id, geometry=False) -> Finding:
    return Finding(
        id=f"f-{dataset_id}",
        area="flood",
        status=FindingStatus.PRESENT,
        statement="Parcel intersects FEMA zone AE per NFHL panel 12127C0340H.",
        evidence={"geometry_wkt": "POINT(-81 29)"} if geometry else {},
        citation=SourceCitation(
            dataset_id=dataset_id,
            provider_id="fema_nfhl",
            feature_keys=["1"],
            retrieved_at=NOW,
            registry_version="0.1.0",
        ),
        mandatory=True,
    )


def _registry(**perms):
    reg = load_registry().model_copy(deep=True)
    for ds_id, kv in perms.items():
        for k, v in kv.items():
            setattr(reg.dataset(ds_id).permissions, k, v)
    return reg


def test_report_null_dataset_removed() -> None:
    reg = _registry()
    kept, excluded = RightsFilter(reg).filter_findings(
        [_finding("ortho_2024")]
    )
    assert kept == []
    assert any("ortho_2024" in r and "report" in r for r in excluded)


def test_display_null_strips_geometry_keeps_text() -> None:
    reg = _registry(nfhl_flood={"report": True, "display": None})
    kept, excluded = RightsFilter(reg).filter_findings(
        [_finding("nfhl_flood", geometry=True)]
    )
    assert len(kept) == 1
    assert kept[0].statement.startswith("Parcel intersects")
    assert "geometry_wkt" not in kept[0].evidence
    assert any("display" in r for r in excluded)


def test_imagery_mode() -> None:
    assert RightsFilter(_registry()).imagery_mode() == "denied"
    licensed = _registry(ortho_2024={"display": True, "report": True})
    assert RightsFilter(licensed).imagery_mode() == "licensed"


def test_map_layers_excludes_display_denied() -> None:
    reg = _registry(nfhl_flood={"report": True})
    kept, _ = RightsFilter(reg).filter_findings(
        [_finding("nfhl_flood", geometry=True)]
    )
    layers = RightsFilter(reg).map_layers(kept)
    # nfhl display is True in the registry -> layer survives.
    assert layers == ["nfhl_flood"]

    reg2 = _registry(nfhl_flood={"report": True, "display": None})
    kept2, _ = RightsFilter(reg2).filter_findings(
        [_finding("nfhl_flood", geometry=True)]
    )
    assert RightsFilter(reg2).map_layers(kept2) == []
