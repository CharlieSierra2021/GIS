"""Dev seed — serves the API + portal with two pre-seeded jobs.

Builds a JobRunner on the toy parcel fixtures and stub evidence (the same
fixtures the tests use — no real endpoints), submits one published job
("123 Main St") and one job awaiting customer input ("500 Ocean Blvd",
ambiguous condo units), then starts uvicorn.

Usage::

    scripts/start_portal.bat        # Windows — picks a free port, opens browser
    scripts/start_portal.sh         # bash — same
    .venv/Scripts/python scripts/dev_seed.py --port 8010 --no-open

Options: ``--port`` (default auto-picks 8010-8029), ``--host``,
``--no-open`` to skip the browser launch.
"""

import argparse
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shapely.geometry import box

from analysis.profile import load_profile
from jurisdiction import AuthorityBoundary, JurisdictionRouter
from reports.publisher import ReportPublisher
from resolution.intake import IntakeKind, IntakeRequest
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source
from tests.support.stubs import NOW, StubFetcher, publishable_registry, toy_pages
from workers import runtime
from workers.audit import InMemoryAuditLog
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner
from workers.storage import InMemoryEvidenceStore

ACCOUNT = "acct-1"
PORT_RANGE = range(8010, 8030)


def find_port(preferred: int | None, host: str) -> int:
    candidates = [preferred] if preferred else list(PORT_RANGE)
    for port in candidates:
        with socket.socket() as sock:
            if sock.connect_ex((host, port)) != 0:
                return port
    raise SystemExit(f"No free port (tried {candidates}); pass --port <n>.")


def open_when_ready(url: str, host: str, port: int) -> None:
    """Open the browser once /health answers (daemon thread)."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1)
            webbrowser.open(url)
            return
        except OSError:
            time.sleep(0.25)


def build_runner() -> JobRunner:
    registry = publishable_registry()
    return JobRunner(
        store=InMemoryJobStore(),
        resolver=ParcelResolver(build_source()),
        router=JurisdictionRouter(
            registry=registry,
            county_boundary=box(-100, -100, 100, 100),
            municipal_boundaries=[AuthorityBoundary("deland", box(0, 0, 15, 15))],
        ),
        fetcher=StubFetcher(toy_pages()),
        registry=registry,
        profile=load_profile(),
        clock=lambda: NOW,
        publisher=ReportPublisher(registry, clock=lambda: NOW),
        audit=InMemoryAuditLog(),
        evidence_store=InMemoryEvidenceStore(),
    )


def main(port: int | None, host: str, open_browser: bool) -> None:
    runner = build_runner()

    published = runner.submit(
        ACCOUNT, IntakeRequest(kind=IntakeKind.ADDRESS, address="123 Main St")
    )
    runner.publish(published.id, ACCOUNT)
    awaiting = runner.submit(
        ACCOUNT, IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
    )

    url = f"http://localhost:{port}/portal?account={ACCOUNT}"
    print("Property Intel - sample data workspace")
    print(f"  portal:         {url}")
    print(f"  health:         http://localhost:{port}/health")
    print(f"  published job:  {published.id}")
    print(f"  awaiting job:   {awaiting.id}")
    print("  (Ctrl+C to stop)\n")

    runtime.set_runner(runner)
    import uvicorn

    from api.main import create_app

    if open_browser:
        threading.Thread(
            target=open_when_ready, args=(url, host, port), daemon=True
        ).start()
    uvicorn.run(create_app(runner, demo_mode=True), host=host, port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to serve on (default: first free in 8010-8029)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--no-open", action="store_true", help="Do not open the browser automatically"
    )
    args = parser.parse_args()
    main(find_port(args.port, args.host), args.host, not args.no_open)
