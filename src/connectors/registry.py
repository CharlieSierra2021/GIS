"""Source registry loader — rights model for registry/volusia.yaml.

Implements SRS §3.5 (REQ-REG): null = unknown = denied for every permission.
See docs/ICD-FL-001.md §11 for the normative rights matrix and §19 for the
registry schema.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

Permission = Literal[
    "discover",
    "query",
    "download",
    "cache",
    "retain_derived",
    "display",
    "report",
    "redistribute",
]

PERMISSION_NAMES: tuple[Permission, ...] = (
    "discover",
    "query",
    "download",
    "cache",
    "retain_derived",
    "display",
    "report",
    "redistribute",
)

# Normative task catalogue, ICD §8.
TASK_TYPES = frozenset(
    {
        "resolve_parcel",
        "route_jurisdiction",
        "fetch_source",
        "fetch_parcels",
        "fetch_fema_flood",
        "fetch_nwi",
        "fetch_soils",
        "fetch_permits",
        "fetch_contamination",
        "fetch_landuse",
        "fetch_ortho",
        "screen_profile",
        "quality_gates",
        "publish_report",
        "refresh_source",
        "drift_check",
        "registry_sync",
    }
)

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "registry" / "volusia.yaml"


class Permissions(BaseModel):
    """The eight per-dataset rights. None means unknown, which is denied."""

    discover: bool | None = None
    query: bool | None = None
    download: bool | None = None
    cache: bool | None = None
    retain_derived: bool | None = None
    display: bool | None = None
    report: bool | None = None
    redistribute: bool | None = None

    def allows(self, perm: Permission) -> bool:
        """True only when the permission is explicitly true (REQ-REG-02)."""
        return getattr(self, perm) is True

    def denied(self, perm: Permission) -> bool:
        return not self.allows(perm)

    def unknown(self) -> list[Permission]:
        return [p for p in PERMISSION_NAMES if getattr(self, p) is None]


class License(BaseModel):
    name: str | None = None
    ref: str | None = None
    gate: str | None = None


class Freshness(BaseModel):
    policy: str | None = None
    max_age_days: int | None = None


class Vintage(BaseModel):
    observation: str | None = None
    publication: str | None = None


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    access_type: Literal["arcgis_query", "file_download", "document_retrieval", "records_request"]
    endpoint: str | None = None
    layer_id: int | None = None
    native_crs: str | None = None
    join_key: str | None = None
    per_authority: bool = False
    expected_fields: list[dict] = []
    freshness: Freshness | None = None
    vintage: Vintage | None = None
    license: License = License()
    permissions: Permissions
    status: Literal["registered", "implementation-ready", "denied"]
    tasks: list[str] = []


class Provider(BaseModel):
    id: str
    name: str
    base_url: str | None = None
    access: str | None = None


class PlanningAuthority(BaseModel):
    id: str
    name: str
    type: Literal["county", "municipal"]


class Registry(BaseModel):
    """Top-level registry document. Unknown top-level keys (e.g. _x_* yaml
    anchor fragments) are ignored."""

    registry_version: str
    activation: str
    jurisdiction: str
    planning_authorities: list[PlanningAuthority] = []
    providers: list[Provider] = []
    datasets: list[Dataset] = []

    def dataset(self, id: str) -> Dataset:
        for ds in self.datasets:
            if ds.id == id:
                return ds
        raise KeyError(id)

    def provider(self, id: str) -> Provider:
        for p in self.providers:
            if p.id == id:
                return p
        raise KeyError(id)

    def authority(self, id: str) -> PlanningAuthority:
        for a in self.planning_authorities:
            if a.id == id:
                return a
        raise KeyError(id)

    def validate_integrity(self) -> list[str]:
        problems: list[str] = []

        provider_ids = {p.id for p in self.providers}

        dataset_ids = [d.id for d in self.datasets]
        for ds_id in sorted({i for i in dataset_ids if dataset_ids.count(i) > 1}):
            problems.append(f"duplicate dataset id: {ds_id}")

        authority_ids = [a.id for a in self.planning_authorities]
        for a_id in sorted({i for i in authority_ids if authority_ids.count(i) > 1}):
            problems.append(f"duplicate planning authority id: {a_id}")

        counties = [a for a in self.planning_authorities if a.type == "county"]
        if len(counties) != 1:
            problems.append(f"expected exactly one county authority, found {len(counties)}")

        for ds in self.datasets:
            if ds.provider not in provider_ids:
                problems.append(f"dataset {ds.id}: unknown provider {ds.provider}")
            for task in ds.tasks:
                if task not in TASK_TYPES:
                    problems.append(f"dataset {ds.id}: unknown task {task}")
            if ds.permissions.allows("redistribute") and not ds.license.ref:
                problems.append(
                    f"dataset {ds.id}: redistribute allowed without license.ref"
                )

        return problems


def load_registry(path: Path | None = None) -> Registry:
    """Load and validate a registry YAML file (default: registry/volusia.yaml)."""
    path = path or DEFAULT_REGISTRY_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Registry.model_validate(data)
