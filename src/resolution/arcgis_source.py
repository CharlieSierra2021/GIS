"""ParcelSource backed by an ArcGIS parcel layer (basemap_parcels/CAMA)."""

import re

from pydantic import BaseModel
from shapely.geometry import Point

from connectors.contract import Connector, Feature, QueryRequest
from resolution.intake import normalize_address
from resolution.models import ParcelCandidate

_PID_RE = re.compile(r"^[A-Za-z0-9\-_. ']+$")


class ParcelFieldMap(BaseModel):
    """Registry-side field names for parcel-layer attributes (ICD §9)."""

    parcel_id: str = "PARID"
    situs: str = "SITUS"
    unit: str | None = "UNIT"
    condo_flag: str | None = None
    parent_parcel_id: str | None = None


def _escape(value: str) -> str:
    return value.replace("'", "''")


class ArcGISParcelSource:
    def __init__(self, connector: Connector, *, field_map: ParcelFieldMap) -> None:
        self._connector = connector
        self._map = field_map

    def by_parcel_id(self, pid: str) -> list[ParcelCandidate]:
        if not _PID_RE.match(pid):
            raise ValueError(f"invalid parcel id {pid!r}")
        where = f"{self._map.parcel_id} = '{_escape(pid)}'"
        return [
            cand for cand in self._query(where=where) if cand.parcel_id == pid
        ]

    def by_address(self, street_normalized: str) -> list[ParcelCandidate]:
        token = street_normalized.split()[0] if street_normalized.split() else ""
        where = f"UPPER({self._map.situs}) LIKE '{_escape(token)}%'"
        return [
            cand
            for cand in self._query(where=where)
            if cand.situs_address
            and normalize_address(cand.situs_address).street == street_normalized
        ]

    def intersecting(self, geometry_wkt: str) -> list[ParcelCandidate]:
        return self._query(geometry_wkt=geometry_wkt)

    def containing_point(self, x: float, y: float) -> list[ParcelCandidate]:
        return self._query(geometry_wkt=Point(x, y).wkt)

    # -- internals ----------------------------------------------------------

    def _query(
        self, where: str | None = None, geometry_wkt: str | None = None
    ) -> list[ParcelCandidate]:
        page = self._connector.query(
            QueryRequest(
                where=where or "1=1",
                geometry_wkt=geometry_wkt,
            )
        )
        return [self._to_candidate(f) for f in page.features]

    def _to_candidate(self, feat: Feature) -> ParcelCandidate:
        m = self._map
        attrs = feat.attributes
        unit = attrs.get(m.unit) if m.unit else None
        condo = bool(unit)
        if m.condo_flag and attrs.get(m.condo_flag):
            condo = True
        return ParcelCandidate(
            parcel_id=str(attrs.get(m.parcel_id)),
            situs_address=attrs.get(m.situs),
            unit=str(unit) if unit else None,
            geometry_wkt=feat.geometry_wkt,
            is_condo_unit=condo,
            parent_parcel_id=(
                str(attrs[m.parent_parcel_id])
                if m.parent_parcel_id and attrs.get(m.parent_parcel_id)
                else None
            ),
        )
