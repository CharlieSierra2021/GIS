import pytest

from tests.support.stubs import (  # noqa: F401  (re-exported for test modules)
    NOW,
    PARCEL_WKT,
    StubFetcher,
    feat,
    full_pages,
    page,
)
from tests.support.stubs import granted_registry as _granted_registry


@pytest.fixture()
def granted_registry():
    return _granted_registry()
