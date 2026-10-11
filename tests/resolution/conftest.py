import pytest

from resolution.fixtures import InMemoryParcelSource
from resolution.resolver import ParcelResolver
from tests.support.parcels import build_source


@pytest.fixture(scope="module")
def source() -> InMemoryParcelSource:
    return build_source()


@pytest.fixture(scope="module")
def resolver(source: InMemoryParcelSource) -> ParcelResolver:
    return ParcelResolver(source)
