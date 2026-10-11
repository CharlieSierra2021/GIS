from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from api.main import create_app

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "registry" / "volusia.yaml"


def test_health() -> None:
    expected_version = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))[
        "registry_version"
    ]
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["registry_version"] == expected_version
