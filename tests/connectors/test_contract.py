from datetime import UTC, datetime

from connectors.contract import FieldSpec, Provenance, compute_fingerprint


def _fields() -> list[FieldSpec]:
    return [
        FieldSpec(name="PARID", type="esriFieldTypeString", nullable=False),
        FieldSpec(name="OBJECTID", type="esriFieldTypeOID", nullable=False),
        FieldSpec(name="SITUS", type="esriFieldTypeString"),
    ]


def test_fingerprint_stable_under_field_reordering() -> None:
    a = compute_fingerprint(_fields(), "EPSG:2881", 0)
    b = compute_fingerprint(list(reversed(_fields())), "EPSG:2881", 0)
    assert a == b


def test_fingerprint_changes_on_type_change() -> None:
    a = compute_fingerprint(_fields(), "EPSG:2881", 0)
    changed = [
        FieldSpec(name="PARID", type="esriFieldTypeInteger", nullable=False),
        FieldSpec(name="OBJECTID", type="esriFieldTypeOID", nullable=False),
        FieldSpec(name="SITUS", type="esriFieldTypeString"),
    ]
    assert compute_fingerprint(changed, "EPSG:2881", 0) != a


def test_fingerprint_changes_on_crs_or_layer() -> None:
    a = compute_fingerprint(_fields(), "EPSG:2881", 0)
    assert compute_fingerprint(_fields(), "EPSG:4326", 0) != a
    assert compute_fingerprint(_fields(), "EPSG:2881", 1) != a


def test_provenance_dates_independent() -> None:
    prov = Provenance(
        dataset_id="basemap_parcels",
        source_feature_key="101",
        retrieved_at=datetime.now(UTC),
        native_crs="EPSG:2881",
    )
    assert prov.retrieved_at is not None
    assert prov.observation_date is None
    assert prov.publication_date is None
