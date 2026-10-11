import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

REPO = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_head(tmp_path) -> None:
    db = tmp_path / "mig.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    tables = set(inspect(create_engine(f"sqlite:///{db}")).get_table_names())
    assert {
        "jobs",
        "audit_events",
        "evidence_artifacts",
        "records_requests",
    } <= tables
