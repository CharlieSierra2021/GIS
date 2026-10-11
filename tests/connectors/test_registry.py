from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from connectors.registry import (
    PERMISSION_NAMES,
    Dataset,
    Permissions,
    Registry,
    load_registry,
)

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "registry" / "volusia.yaml"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry()


def test_registry_loads_and_passes_integrity(registry: Registry) -> None:
    assert registry.validate_integrity() == []


def test_eighteen_authorities_exactly_one_county(registry: Registry) -> None:
    assert len(registry.planning_authorities) == 18
    counties = [a for a in registry.planning_authorities if a.type == "county"]
    assert len(counties) == 1
    assert counties[0].id == "volusia_uninc"


def test_ortho_display_and_report_denied_and_unknown(registry: Registry) -> None:
    perms = registry.dataset("ortho_2024").permissions
    assert perms.denied("display")
    assert perms.denied("report")
    assert "display" in perms.unknown()
    assert "report" in perms.unknown()


def test_redistribute_denied_for_every_dataset(registry: Registry) -> None:
    for ds in registry.datasets:
        assert ds.permissions.denied("redistribute"), ds.id


def test_nfhl_display_allowed_report_denied(registry: Registry) -> None:
    perms = registry.dataset("nfhl_flood").permissions
    assert perms.allows("display") is True
    assert perms.allows("report") is False


def test_all_none_permissions_deny_all() -> None:
    perms = Permissions()
    assert perms.unknown() == list(PERMISSION_NAMES)
    for perm in PERMISSION_NAMES:
        assert perms.allows(perm) is False
        assert perms.denied(perm) is True


def test_unknown_dataset_raises_keyerror(registry: Registry) -> None:
    with pytest.raises(KeyError):
        registry.dataset("not_a_dataset")


def test_bogus_task_name_is_integrity_problem(tmp_path: Path) -> None:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    data["datasets"][0]["tasks"].append("not_a_task")
    tampered = tmp_path / "tampered.yaml"
    tampered.write_text(yaml.safe_dump(data), encoding="utf-8")
    problems = load_registry(tampered).validate_integrity()
    assert any("not_a_task" in p for p in problems)


def test_registry_environment_path(monkeypatch, tmp_path: Path) -> None:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    data["registry_version"] = "environment-test"
    configured = tmp_path / "configured.yaml"
    configured.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("PI_REGISTRY_PATH", str(configured))
    assert load_registry().registry_version == "environment-test"
    expected = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))["registry_version"]
    assert load_registry(REGISTRY_PATH).registry_version == expected


def test_missing_configured_registry_does_not_fall_back(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PI_REGISTRY_PATH", str(tmp_path / "missing.yaml"))
    with pytest.raises(FileNotFoundError):
        load_registry()


def test_extra_dataset_field_fails_validation() -> None:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    dataset_data = data["datasets"][0]
    dataset_data["bogus_field"] = 1
    with pytest.raises(ValidationError):
        Dataset.model_validate(dataset_data)
