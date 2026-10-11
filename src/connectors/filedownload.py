"""file_download connector — ICD §5.2-E / §6 (federal/static downloads).

A file_download dataset has no queryable spatial endpoint: the artefact is
downloaded wholesale (respecting the ``download`` right — denied/unknown
refuses before any request), cached under ``cache_dir`` keyed by content
hash, and ingested locally (see ``ingest_geojson``). ``query()`` therefore
always raises SOURCE_UNAVAILABLE — these datasets are queried after local
ingest, not over the wire.

Conditional GETs honour ``DownloadRequest.previous``: ETag and
Last-Modified are sent as If-None-Match / If-Modified-Since and a 304
returns the previous ``ObjectRef`` untouched.
"""

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from connectors.contract import (
    Capabilities,
    ConnectorError,
    DownloadRequest,
    FailureClass,
    FeaturePage,
    FieldSpec,
    HealthStatus,
    ObjectRef,
    QueryRequest,
    ServiceDescriptor,
    compute_fingerprint,
)
from connectors.registry import Dataset

_CHUNK = 1 << 16


class FileDownloadConnector:
    def __init__(
        self,
        provider_id: str,
        dataset: Dataset,
        url: str,
        *,
        client: httpx.Client | None = None,
        cache_dir: Path,
        max_retries: int = 3,
        timeout: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._provider_id = provider_id
        self._dataset = dataset
        self._url = url
        self._client = client or httpx.Client(timeout=timeout)
        self._cache_dir = Path(cache_dir)
        self._max_retries = max_retries
        self._sleep = sleep

    # -- contract -----------------------------------------------------------

    def describe(self) -> ServiceDescriptor:
        """Pseudo-descriptor from HEAD headers — file downloads have no
        schema endpoint, so content-type/length stand in as fields."""
        resp = self._head()
        headers = resp.headers
        fields = [
            FieldSpec(name="content-type", type=headers.get("content-type", "unknown")),
            FieldSpec(name="content-length", type=headers.get("content-length", "unknown")),
        ]
        fingerprint = compute_fingerprint(fields, None, None)
        # Include volatile validators so drift on the artefact itself is
        # visible, not just the header "schema".
        fingerprint = hashlib.sha256(
            (
                fingerprint
                + (headers.get("etag") or "")
                + (headers.get("content-length") or "")
                + (headers.get("content-type") or "")
            ).encode("utf-8")
        ).hexdigest()
        return ServiceDescriptor(
            provider_id=self._provider_id,
            dataset_id=self._dataset.id,
            endpoint=self._url,
            fields=fields,
            fingerprint=fingerprint,
        )

    def capabilities(self) -> Capabilities:
        return Capabilities(
            pagination=False, query_types=[], crs=[]
        )

    def query(self, req: QueryRequest) -> FeaturePage:
        raise ConnectorError(
            FailureClass.SOURCE_UNAVAILABLE,
            detail=(
                "file_download datasets are queried after local ingest; "
                "use download() then an ingest step"
            ),
        )

    def health(self) -> HealthStatus:
        try:
            desc = self.describe()
        except ConnectorError as exc:
            return HealthStatus(
                ok=False,
                checked_at=datetime.now(UTC),
                detail=f"{exc.failure_class.value}: {exc.detail}",
            )
        return HealthStatus(
            ok=True, fingerprint=desc.fingerprint, checked_at=datetime.now(UTC)
        )

    # -- download -----------------------------------------------------------

    def download(self, req: DownloadRequest) -> ObjectRef:
        if not self._dataset.permissions.allows("download"):
            raise ConnectorError(
                FailureClass.PERMISSION_DENIED,
                detail=f"registry denies download for {self._dataset.id}",
            )
        url = req.url or self._url
        headers = {}
        if req.previous:
            if req.previous.etag:
                headers["If-None-Match"] = req.previous.etag
            if req.previous.last_modified:
                headers["If-Modified-Since"] = req.previous.last_modified

        resp = self._get(url, headers=headers)
        if resp.status_code == 304:
            return req.previous

        content = resp.content
        digest = hashlib.sha256(content).hexdigest()
        ext = _extension(url, resp.headers.get("content-type"))
        path = (
            self._cache_dir
            / self._dataset.id
            / f"{digest[:16]}{ext}"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return ObjectRef(
            dataset_id=self._dataset.id,
            url=url,
            path=str(path),
            sha256=digest,
            bytes=len(content),
            retrieved_at=datetime.now(UTC),
            content_type=resp.headers.get("content-type"),
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )

    # -- internals ----------------------------------------------------------

    def _head(self) -> httpx.Response:
        last_exc: ConnectorError | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._client.head(self._url)
            except httpx.TransportError as exc:
                last_exc = ConnectorError(
                    FailureClass.SOURCE_UNAVAILABLE, detail=str(exc)
                )
            else:
                if resp.status_code in (401, 403):
                    raise ConnectorError(
                        FailureClass.PERMISSION_DENIED,
                        detail=f"HTTP {resp.status_code} from {self._url}",
                    )
                if resp.status_code >= 400:
                    last_exc = ConnectorError(
                        FailureClass.SOURCE_UNAVAILABLE,
                        detail=f"HTTP {resp.status_code} from {self._url}",
                    )
                else:
                    return resp
            if attempt < self._max_retries - 1:
                self._sleep(0.5 * (2**attempt))
        raise last_exc or ConnectorError(
            FailureClass.SOURCE_UNAVAILABLE, detail=f"no response from {self._url}"
        )

    def _get(self, url: str, headers: dict) -> httpx.Response:
        last_exc: ConnectorError | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.TransportError as exc:
                last_exc = ConnectorError(
                    FailureClass.SOURCE_UNAVAILABLE, detail=str(exc)
                )
            else:
                if resp.status_code in (401, 403):
                    raise ConnectorError(
                        FailureClass.PERMISSION_DENIED,
                        detail=f"HTTP {resp.status_code} from {url}",
                    )
                if resp.status_code >= 500:
                    last_exc = ConnectorError(
                        FailureClass.SOURCE_UNAVAILABLE,
                        detail=f"HTTP {resp.status_code} from {url}",
                    )
                elif resp.status_code >= 400 and resp.status_code != 304:
                    raise ConnectorError(
                        FailureClass.SOURCE_UNAVAILABLE,
                        detail=f"HTTP {resp.status_code} from {url}",
                    )
                else:
                    return resp
            if attempt < self._max_retries - 1:
                self._sleep(0.5 * (2**attempt))
        raise last_exc or ConnectorError(
            FailureClass.SOURCE_UNAVAILABLE, detail=f"no response from {url}"
        )


def _extension(url: str, content_type: str | None) -> str:
    suffix = Path(url.split("?")[0]).suffix
    if suffix:
        return suffix
    if content_type and "geo+json" in content_type:
        return ".geojson"
    if content_type and "json" in content_type:
        return ".json"
    if content_type and "zip" in content_type:
        return ".zip"
    return ".bin"
