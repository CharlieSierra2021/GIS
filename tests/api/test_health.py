import os
import shutil
import subprocess
import sys
import zipfile
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


def test_installed_wheel_starts_outside_checkout(tmp_path: Path) -> None:
    root = REGISTRY_PATH.parents[1]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(root / name, source / name)
    shutil.copytree(root / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    wheels = tmp_path / "wheels"
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels), str(source)],
        check=True, capture_output=True, text=True, timeout=180,
    )
    wheel, = wheels.glob("property_intel-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        for resource in (
            "analysis/profiles/florida_land_screening_v1.yaml",
            "reports/templates/report.html.j2",
            "reports/templates/portal/base.html.j2",
            "reports/templates/portal/index.html.j2",
            "reports/templates/portal/job.html.j2",
        ):
            assert resource in archive.namelist(), resource
    installed = tmp_path / "installed"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed), str(wheel)],
        check=True, capture_output=True, text=True, timeout=90,
    )
    env = dict(os.environ, PYTHONPATH=str(installed), PI_REGISTRY_PATH=str(REGISTRY_PATH))
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
from pathlib import Path
import api
from api.main import create_app
from api.templating import make_env
from analysis.profile import load_profile
from fastapi.testclient import TestClient
assert Path(api.__file__).is_relative_to(Path(sys.argv[1]))
assert len(load_profile().areas) == 9
for name in ('report.html.j2', 'portal/base.html.j2', 'portal/index.html.j2', 'portal/job.html.j2'):
    make_env().get_template(name)
with TestClient(create_app()) as client:
    response = client.get('/health')
    assert response.status_code == 200, response.text
    assert response.json()['activation'] == 'FL-001'
    response = client.get('/portal?account=wheel-smoke')
    assert response.status_code == 200, response.text
print('Installed wheel health, portal, profile and templates OK')
""", str(installed)],
        check=False, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
