"""ArcGIS REST Feature Service adapter — ICD §5, access_type arcgis_query.

Registry rights are enforced at the connector boundary: ``query()`` refuses
before any network call when the dataset's ``query`` permission is not
explicitly true (SRS REQ-REG-02). ``describe()`` is permitted under
``discover`` and always returns live metadata (CON-A).
"""

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from shapely import from_wkt
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon

from connectors.contract import (
    Capabilities,
    ConnectorError,
    FailureClass,
    Feature,
    FeaturePage,
    FieldSpec,
    HealthStatus,
    Provenance,
    QueryRequest,
    ServiceDescriptor,
    compute_fingerprint,
)
from connectors.registry import Dataset

_DENIED_CODES = {403, 498, 499}

_SPATIAL_REL = {
    "intersects": "esriSpatialRelIntersects",
    "contains": "esriSpatialRelContains",
    "within": "esriSpatialRelWithin",
}


class ArcGISFeatureServiceConnector:
    def __init__(
        self,
        provider_id: str,
        dataset: Dataset,
        endpoint: str,
        *,
        client: httpx.Client | None = None,
        max_retries: int = 3,
        timeout: float = 20.0,
        expected_fingerprint: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._provider_id = provider_id
        self._dataset = dataset
        self._endpoint = endpoint.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        self._max_retries = max_retries
        self._expected_fingerprint = expected_fingerprint
        self._sleep = sleep

    # -- contract -----------------------------------------------------------

    def describe(self) -> ServiceDescriptor:
        meta = self._get_json(self._endpoint)
        wkid = None
        sr = (meta.get("extent") or {}).get("spatialReference") or {}
        if sr.get("latestWkid") or sr.get("wkid"):
            wkid = f"EPSG:{sr.get('latestWkid') or sr.get('wkid')}"
        fields = [
            FieldSpec(
                name=f["name"],
                type=f["type"],
                nullable=f.get("nullable", True),
            )
            for f in meta.get("fields", [])
        ]
        layer_id = meta.get("id")
        return ServiceDescriptor(
            provider_id=self._provider_id,
            dataset_id=self._dataset.id,
            endpoint=self._endpoint,
            layer_id=layer_id,
            layer_name=meta.get("name"),
            native_crs=wkid,
            fields=fields,
            max_record_count=meta.get("maxRecordCount"),
            supports_pagination=bool(
                (meta.get("advancedQueryCapabilities") or {}).get(
                    "supportsPagination", False
                )
            ),
            fingerprint=compute_fingerprint(fields, wkid, layer_id),
        )

    def capabilities(self) -> Capabilities:
        desc = self.describe()
        return Capabilities(
            pagination=desc.supports_pagination,
            max_features=desc.max_record_count,
            query_types=["spatial", "attribute"],
            crs=[desc.native_crs] if desc.native_crs else [],
        )

    def query(self, req: QueryRequest) -> FeaturePage:
        if not self._dataset.permissions.allows("query"):
            raise ConnectorError(
                FailureClass.PERMISSION_DENIED,
                detail=f"registry denies query for {self._dataset.id}",
            )

        desc = self.describe()
        if (
            self._expected_fingerprint
            and desc.fingerprint != self._expected_fingerprint
        ):
            raise ConnectorError(
                FailureClass.SCHEMA_DRIFT,
                detail=(
                    f"live fingerprint {desc.fingerprint} != expected "
                    f"{self._expected_fingerprint} for {self._dataset.id}"
                ),
            )

        params: dict[str, str] = {
            "f": "json",
            "where": req.where,
            "outFields": ",".join(req.out_fields) if req.out_fields else "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "resultOffset": str(req.offset),
        }
        if req.limit is not None:
            params["resultRecordCount"] = str(req.limit)
        if req.geometry_wkt:
            geom = from_wkt(req.geometry_wkt)
            params["geometry"] = json.dumps(self._esri_geometry(geom))
            params["geometryType"] = self._esri_geometry_type(geom)
            params["spatialRel"] = _SPATIAL_REL[req.spatial_rel]
            params["inSR"] = "4326"

        page = self._get_json(f"{self._endpoint}/query", params=params)

        oid_field = self._object_id_field(desc)
        features = [
            Feature(
                key=str(f.get("attributes", {}).get(oid_field))
                if oid_field
                else str(i),
                attributes=dict(f.get("attributes") or {}),
                geometry_wkt=self._geometry_to_wkt(f.get("geometry")),
                provenance=Provenance(
                    dataset_id=self._dataset.id,
                    source_feature_key=str(f.get("attributes", {}).get(oid_field))
                    if oid_field
                    else str(i),
                    retrieved_at=datetime.now(UTC),
                    native_crs=desc.native_crs,
                ),
            )
            for i, f in enumerate(page.get("features", []))
        ]
        exceeded = bool(page.get("exceededTransferLimit"))
        return FeaturePage(
            features=features,
            next_offset=req.offset + len(features) if exceeded else None,
            exceeded_limit=exceeded,
        )

    def health(self) -> HealthStatus:
        try:
            desc = self.describe()
        except ConnectorError as exc:
            return HealthStatus(
                ok=False,
                fingerprint=None,
                checked_at=datetime.now(UTC),
                detail=f"{exc.failure_class.value}: {exc.detail}",
            )
        return HealthStatus(
            ok=True,
            fingerprint=desc.fingerprint,
            checked_at=datetime.now(UTC),
            detail=None,
        )

    # -- internals ----------------------------------------------------------

    def _object_id_field(self, desc: ServiceDescriptor) -> str | None:
        for f in desc.fields:
            if f.type == "esriFieldTypeOID":
                return f.name
        return desc.fields[0].name if desc.fields else None

    def _get_json(self, url: str, params: dict | None = None) -> dict:
        last_exc: ConnectorError | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._client.get(url, params=params)
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
                elif resp.status_code >= 400:
                    raise ConnectorError(
                        FailureClass.SOURCE_UNAVAILABLE,
                        detail=f"HTTP {resp.status_code} from {url}",
                    )
                else:
                    return self._parse(resp.json(), url)
            if attempt < self._max_retries - 1:
                self._sleep(0.5 * (2**attempt))
        raise last_exc or ConnectorError(
            FailureClass.SOURCE_UNAVAILABLE, detail=f"no response from {url}"
        )

    def _parse(self, payload: dict, url: str) -> dict:
        error = payload.get("error")
        if error:
            code = error.get("code")
            if code in _DENIED_CODES:
                raise ConnectorError(
                    FailureClass.PERMISSION_DENIED,
                    detail=f"ArcGIS error {code}: {error.get('message')}",
                )
            raise ConnectorError(
                FailureClass.SOURCE_UNAVAILABLE,
                detail=f"ArcGIS error {code}: {error.get('message')} from {url}",
            )
        return payload

    @staticmethod
    def _esri_geometry(geom) -> dict:
        sr = {"spatialReference": {"wkid": 4326}}
        if geom.geom_type == "Point":
            return {"x": geom.x, "y": geom.y, **sr}
        if geom.geom_type == "Polygon":
            rings = [list(geom.exterior.coords)] + [
                list(r.coords) for r in geom.interiors
            ]
            return {"rings": rings, **sr}
        if geom.geom_type == "MultiPolygon":
            rings = []
            for part in geom.geoms:
                rings.append(list(part.exterior.coords))
                rings.extend(list(r.coords) for r in part.interiors)
            return {"rings": rings, **sr}
        raise ConnectorError(
            FailureClass.SOURCE_UNAVAILABLE,
            detail=f"unsupported query geometry type {geom.geom_type}",
        )

    @staticmethod
    def _esri_geometry_type(geom) -> str:
        return {
            "Point": "esriGeometryPoint",
            "Polygon": "esriGeometryPolygon",
            "MultiPolygon": "esriGeometryPolygon",
        }[geom.geom_type]

    @staticmethod
    def _geometry_to_wkt(geometry: dict | None) -> str | None:
        if not geometry:
            return None
        if "rings" in geometry:
            rings = geometry["rings"]
            geom: object = (
                Polygon(rings[0])
                if len(rings) == 1
                else MultiPolygon([Polygon(r) for r in rings])
            )
        elif "paths" in geometry:
            paths = geometry["paths"]
            geom = (
                LineString(paths[0])
                if len(paths) == 1
                else MultiLineString(paths)
            )
        elif "x" in geometry and "y" in geometry:
            geom = Point(geometry["x"], geometry["y"])
        else:
            return None
        return geom.wkt
