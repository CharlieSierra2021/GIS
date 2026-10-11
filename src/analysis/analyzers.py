"""Per-area analyzers — ICD §10 left-column phrasing only.

Each returns ``(statement, evidence, disclosure)``. Statements must pass
``check_boundary_language``; qualifiers such as "not a flood determination"
belong in ``disclosure``, which is intentionally not boundary-checked.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from shapely import from_wkt
from shapely.ops import unary_union

from analysis.geo import distance_m
from connectors.contract import Feature

if TYPE_CHECKING:
    from analysis.engine import ScreeningContext
    from analysis.profile import AreaSpec


def _date(features: list[Feature]) -> str:
    rt = features[0].provenance.retrieved_at
    if isinstance(rt, datetime):
        return rt.date().isoformat()
    return "unknown"


def _uniq(features: list[Feature], *keys: str) -> list[str]:
    seen = []
    for f in features:
        for k in keys:
            v = f.attributes.get(k)
            if v is not None and str(v) not in seen:
                seen.append(str(v))
    return seen


def flood(area: str, spec: "AreaSpec", features: list[Feature], ctx: "ScreeningContext"):
    zones = _uniq(features, "FLD_ZONE", "ZONE")
    flags = _uniq(features, "SFHA_TF")
    statement = (
        f"Parcel intersects FEMA NFHL flood zone(s) {', '.join(zones) or 'unknown'} "
        f"as retrieved {_date(features)}"
    )
    if flags:
        statement += f"; SFHA flag(s): {', '.join(flags)}"
    statement += "."
    geoms = [from_wkt(f.geometry_wkt) for f in features if f.geometry_wkt]
    evidence = {"zones": zones, "sfha_flags": flags, "feature_count": len(features)}
    if geoms:
        evidence["geometry_wkt"] = unary_union(geoms).wkt
    disclosure = "Screening indicator only; not a lender-compliant determination."
    return statement, evidence, disclosure


def wetlands(area, spec, features, ctx):
    types = _uniq(features, "WETLAND_TYPE", "ATTRIBUTE")
    statement = (
        f"NWI maps {len(features)} wetland feature(s) intersecting the parcel "
        f"({', '.join(types) or 'unknown type'}) as retrieved {_date(features)}."
    )
    geoms = [from_wkt(f.geometry_wkt) for f in features if f.geometry_wkt]
    evidence = {"wetland_types": types, "feature_count": len(features)}
    if geoms:
        evidence["geometry_wkt"] = unary_union(geoms).wkt
    disclosure = "Mapped indicator; not a field determination."
    return statement, evidence, disclosure


def hydric_soils(area, spec, features, ctx):
    units = _uniq(features, "MUSYM", "MUNAME")
    ratings = _uniq(features, "HYDRIC_RATING", "hydclprs")
    statement = (
        f"NRCS map unit(s) {', '.join(units) or 'unknown'} intersect the parcel; "
        f"hydric rating(s): {', '.join(ratings) or 'unknown'} "
        f"as retrieved {_date(features)}."
    )
    evidence = {"map_units": units, "hydric_ratings": ratings}
    disclosure = "Map-unit rating; not an on-site soils description."
    return statement, evidence, disclosure


def proximity(area, spec, features, ctx):
    parcel = from_wkt(ctx.parcel_wkt)
    distances = [
        distance_m(parcel, from_wkt(f.geometry_wkt))
        for f in features
        if f.geometry_wkt
    ]
    nearest = min(distances) if distances else None
    within = (
        sum(1 for d in distances if d <= (spec.buffer_m or 0))
        if spec.buffer_m is not None
        else len(features)
    )
    if within == 0:
        # No qualifying evidence inside the buffer — the engine renders this
        # as NOT_FOUND ("no record"), never PRESENT.
        return None
    label = spec.label or "feature"
    nearest_txt = f"{nearest:.0f}" if nearest is not None else "unknown"
    statement = (
        f"{within} {label}(s) within {spec.buffer_m:.0f} m of the parcel; "
        f"nearest ≈ {nearest_txt} m as retrieved {_date(features)}."
    )
    evidence = {
        "within_buffer": within,
        "nearest_m": round(nearest, 1) if nearest is not None else None,
        "buffer_m": spec.buffer_m,
        "measure_crs": "EPSG:3087",
        "feature_count": len(features),
    }
    return statement, evidence, None


def attribute_list(area, spec, features, ctx):
    label = spec.label or "record"
    statement = (
        f"{len(features)} {label}(s) associated with the parcel "
        f"as retrieved {_date(features)}."
    )
    evidence = {"records": [f.attributes for f in features[:20]]}
    return statement, evidence, None


def land_use(area, spec, features, ctx):
    codes = _uniq(features, "FLU", "FLU_DESC", "LANDUSE")
    name = (
        ctx.registry.authority(ctx.authority_id).name
        if ctx.authority_id
        else "unknown authority"
    )
    statement = (
        f"{name} future land use designation(s): {', '.join(codes) or 'unknown'} "
        f"per {spec.dataset} as retrieved {_date(features)}."
    )
    evidence = {"designations": codes, "authority_id": ctx.authority_id}
    disclosure = (
        "Designation per comprehensive plan; not a zoning or buildability "
        "determination."
    )
    return statement, evidence, disclosure


ANALYZERS = {
    "flood": flood,
    "wetlands": wetlands,
    "hydric_soils": hydric_soils,
    "proximity": proximity,
    "attribute_list": attribute_list,
    "land_use": land_use,
}
