"""Connector validation harness — ICD §5, README §harness.

Verifies a live service against a registered dataset: resolves the layer,
checks expected fields and CRS against the registry, detects schema drift,
and writes a registry-ready fixture record.

Usage:
    python -m connectors.validate --provider volusia_county_gis \\
        --dataset basemap_parcels [--endpoint URL] [--registry path] [--out path]
"""

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from connectors.arcgis import ArcGISFeatureServiceConnector
from connectors.contract import Connector, ConnectorError, ServiceDescriptor
from connectors.registry import Dataset, Provider, load_registry

DEFAULT_OUT = Path("tests/connectors/fixtures")


def _drift_report(dataset: Dataset, desc: ServiceDescriptor) -> list[str]:
    drift: list[str] = []
    live = {f.name: f for f in desc.fields}
    for spec in dataset.expected_fields:
        name = spec.get("name")
        expected_type = spec.get("type")
        if name not in live:
            drift.append(f"expected field {name!r} missing from live service")
        elif expected_type is not None and live[name].type != expected_type:
            drift.append(
                f"field {name!r} type {live[name].type!r} != expected {expected_type!r}"
            )
    if dataset.native_crs and desc.native_crs != dataset.native_crs:
        drift.append(
            f"native_crs {desc.native_crs!r} != registered {dataset.native_crs!r}"
        )
    return drift


def run(
    argv: list[str] | None = None,
    *,
    connector_factory: Callable[[Provider, Dataset, str], Connector] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="connectors.validate")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    registry = load_registry(args.registry)
    try:
        provider = registry.provider(args.provider)
        dataset = registry.dataset(args.dataset)
    except KeyError as exc:
        print(f"error: unknown registry entry {exc}", file=sys.stderr)
        return 2

    endpoint = args.endpoint or dataset.endpoint
    if not endpoint:
        print(
            f"error: no endpoint for dataset {dataset.id!r}; pass --endpoint or "
            f"register one in registry/volusia.yaml",
            file=sys.stderr,
        )
        return 2

    factory = connector_factory or (
        lambda p, d, e: ArcGISFeatureServiceConnector(p.id, d, e)
    )
    connector = factory(provider, dataset, endpoint)

    try:
        desc = connector.describe()
    except ConnectorError as exc:
        print(
            f"error: describe() failed for {dataset.id!r}: "
            f"{exc.failure_class.value}: {exc.detail}",
            file=sys.stderr,
        )
        return 3

    drift = _drift_report(dataset, desc)

    out = args.out or DEFAULT_OUT / f"{provider.id}__{dataset.id}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "provider": provider.id,
        "dataset": dataset.id,
        "endpoint": desc.endpoint,
        "layer_id": desc.layer_id,
        "native_crs": desc.native_crs,
        "fingerprint": desc.fingerprint,
        "fields": [f.model_dump() for f in desc.fields],
        "drift": drift,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    out.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")

    print(f"{provider.id}/{dataset.id}: layer {desc.layer_id} {desc.layer_name!r}")
    print(f"  endpoint {desc.endpoint}")
    print(f"  native_crs {desc.native_crs}  fields {len(desc.fields)}")
    print(f"  fingerprint {desc.fingerprint}")
    print(f"  fixture written to {out}")
    if drift:
        print("  DRIFT DETECTED:")
        for item in drift:
            print(f"    - {item}")
        return 1
    print("  ok: live metadata matches registry expectations")
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
