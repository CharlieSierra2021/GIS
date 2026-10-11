"""Runner singleton for the dev/CI environment.

``build_default_runner`` wires the pipeline over an empty in-memory parcel
source (a real source needs registered endpoints) and a registry-backed
evidence fetcher; jurisdiction routing is disabled (``router=None``) so jobs
degrade to UNRESOLVED routing rather than fail. Endpoints come from the
registry or ConnectorFactory overrides in deployments.
"""

from analysis.profile import load_profile
from connectors.evidence import RegistryEvidenceFetcher
from connectors.factory import ConnectorFactory
from connectors.registry import Registry, load_registry
from resolution.fixtures import InMemoryParcelSource
from resolution.resolver import ParcelResolver
from workers.jobs import InMemoryJobStore
from workers.pipeline import JobRunner

_runner: JobRunner | None = None


def get_runner() -> JobRunner | None:
    return _runner


def set_runner(runner: JobRunner | None) -> None:
    global _runner
    _runner = runner


def build_default_runner(registry: Registry | None = None) -> JobRunner:
    registry = registry or load_registry()
    resolver = ParcelResolver(InMemoryParcelSource([]))
    fetcher = RegistryEvidenceFetcher(ConnectorFactory(registry))
    return JobRunner(
        store=InMemoryJobStore(),
        resolver=resolver,
        router=None,
        fetcher=fetcher,
        registry=registry,
        profile=load_profile(),
    )
