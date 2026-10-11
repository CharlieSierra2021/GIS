import hashlib
from pathlib import Path

import httpx
import pytest

from connectors.contract import (
    ConnectorError,
    DownloadRequest,
    FailureClass,
    QueryRequest,
)
from connectors.filedownload import FileDownloadConnector
from connectors.registry import load_registry

URL = "https://data.example.com/nwi/wetlands.geojson"
PAYLOAD = b'{"type":"FeatureCollection","features":[]}'


def _dataset(download=True):
    reg = load_registry().model_copy(deep=True)
    ds = reg.dataset("nwi_wetlands")
    ds.permissions.download = download
    return ds


def _connector(handler, tmp_path, download=True, **kw):
    return FileDownloadConnector(
        "usfws_nwi",
        _dataset(download),
        URL,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path,
        sleep=lambda s: None,
        **kw,
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=PAYLOAD,
        headers={
            "content-type": "application/geo+json",
            "etag": '"v1"',
            "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT",
        },
    )


def test_download_writes_file_and_hashes(tmp_path) -> None:
    conn = _connector(_ok, tmp_path)
    ref = conn.download(DownloadRequest())
    path = Path(ref.path)
    assert path.read_bytes() == PAYLOAD
    assert ref.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert ref.bytes == len(PAYLOAD)
    assert ref.etag == '"v1"'
    assert ref.last_modified == "Wed, 01 Jan 2025 00:00:00 GMT"
    assert ref.content_type == "application/geo+json"


def test_download_denied_before_request(tmp_path) -> None:
    called = []

    def handler(request):
        called.append(1)
        return httpx.Response(200)

    conn = _connector(handler, tmp_path, download=None)
    with pytest.raises(ConnectorError) as exc:
        conn.download(DownloadRequest())
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED
    assert called == []


def test_304_returns_previous(tmp_path) -> None:
    seen_headers = []

    def handler(request):
        seen_headers.append(dict(request.headers))
        return httpx.Response(304)

    conn = _connector(handler, tmp_path)
    # Build a previous ref via a real download first.
    conn2 = _connector(_ok, tmp_path)
    prev = conn2.download(DownloadRequest())

    ref = conn.download(DownloadRequest(previous=prev))
    assert ref == prev
    assert seen_headers[0].get("if-none-match") == '"v1"'
    assert "if-modified-since" in seen_headers[0]


def test_500_retries_then_source_unavailable(tmp_path) -> None:
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, text="boom")

    conn = _connector(handler, tmp_path)
    with pytest.raises(ConnectorError) as exc:
        conn.download(DownloadRequest())
    assert exc.value.failure_class == FailureClass.SOURCE_UNAVAILABLE
    assert len(calls) == 3


def test_403_is_permission_denied(tmp_path) -> None:
    conn = _connector(lambda r: httpx.Response(403), tmp_path)
    with pytest.raises(ConnectorError) as exc:
        conn.download(DownloadRequest())
    assert exc.value.failure_class == FailureClass.PERMISSION_DENIED


def test_describe_fingerprint_changes_with_etag(tmp_path) -> None:
    def h1(request):
        return httpx.Response(200, headers={"etag": '"a"', "content-length": "10"})

    def h2(request):
        return httpx.Response(200, headers={"etag": '"b"', "content-length": "10"})

    d1 = _connector(h1, tmp_path).describe()
    d2 = _connector(h2, tmp_path).describe()
    assert d1.fingerprint != d2.fingerprint
    assert d1.endpoint == URL


def test_query_raises_documented_message(tmp_path) -> None:
    conn = _connector(_ok, tmp_path)
    with pytest.raises(ConnectorError) as exc:
        conn.query(QueryRequest())
    assert exc.value.failure_class == FailureClass.SOURCE_UNAVAILABLE
    assert "queried after local ingest" in exc.value.detail
