"""Jurisdiction router — SRS REQ-JUR-01..03, ICD §3 and §14.

Routing assigns a parcel polygon to exactly one planning authority (county or
municipal). Authority is derived from geometry overlap only: there is no code
path — and deliberately no ``route_point`` — that derives jurisdiction from a
geocoded point, name, address, or city string. A geocoded point is supporting
evidence, not parcel identity (SRS §1.2 C3); routing takes parcel polygons only.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from shapely.geometry import MultiPolygon, Polygon

from connectors.registry import Registry

Geometry = Polygon | MultiPolygon


class RoutingStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class AuthorityBoundary:
    """One municipal polygon from the mun_boundaries dataset (never county)."""

    authority_id: str
    geometry: Geometry


@dataclass(frozen=True)
class RoutingResult:
    status: RoutingStatus
    authority_id: str | None
    candidates: tuple[str, ...]
    disclosure: str | None
    evidence: dict


class JurisdictionRouter:
    def __init__(
        self,
        registry: Registry,
        county_boundary: Geometry,
        municipal_boundaries: Sequence[AuthorityBoundary],
        *,
        tolerance: float = 0.01,
    ) -> None:
        self._registry = registry
        self._county_boundary = county_boundary
        self._tolerance = tolerance

        county_authorities = [a for a in registry.planning_authorities if a.type == "county"]
        if len(county_authorities) != 1:
            raise ValueError(
                f"registry must contain exactly one county authority, "
                f"found {len(county_authorities)}"
            )
        self._county_id = county_authorities[0].id

        for boundary in municipal_boundaries:
            try:
                authority = registry.authority(boundary.authority_id)
            except KeyError:
                raise ValueError(
                    f"boundary references unknown authority {boundary.authority_id!r}"
                ) from None
            if authority.type != "municipal":
                raise ValueError(
                    f"boundary authority {boundary.authority_id!r} is type "
                    f"{authority.type!r}, expected 'municipal'"
                )
        self._municipal_boundaries = tuple(municipal_boundaries)

    def route(self, parcel: Geometry) -> RoutingResult:
        if parcel.is_empty or parcel.area <= 0:
            raise ValueError("parcel geometry is empty or zero-area")

        parcel_area = parcel.area
        fractions: dict[str, float] = {}
        for boundary in self._municipal_boundaries:
            frac = boundary.geometry.intersection(parcel).area / parcel_area
            # Sliver noise below tolerance is 0; near-total coverage is 1.
            if frac < self._tolerance:
                frac = 0.0
            elif frac > 1.0 - self._tolerance:
                frac = 1.0
            fractions[boundary.authority_id] = frac

        county_frac = self._county_boundary.intersection(parcel).area / parcel_area
        if county_frac > 1.0 - self._tolerance:
            county_frac = 1.0

        evidence = {
            "overlap_fractions": dict(fractions),
            "county_coverage": county_frac,
            "tolerance": self._tolerance,
        }

        positive = {a: f for a, f in fractions.items() if f > 0.0}

        if len(positive) == 1 and next(iter(positive.values())) == 1.0:
            authority_id = next(iter(positive))
            return RoutingResult(
                status=RoutingStatus.RESOLVED,
                authority_id=authority_id,
                candidates=(authority_id,),
                disclosure=None,
                evidence=evidence,
            )

        if not positive:
            if county_frac == 1.0:
                return RoutingResult(
                    status=RoutingStatus.RESOLVED,
                    authority_id=self._county_id,
                    candidates=(self._county_id,),
                    disclosure=None,
                    evidence=evidence,
                )
            return RoutingResult(
                status=RoutingStatus.UNRESOLVED,
                authority_id=None,
                candidates=(),
                disclosure=(
                    "Parcel not within Volusia County boundary coverage; "
                    "jurisdiction-dependent findings omitted."
                ),
                evidence=evidence,
            )

        # AMBIGUOUS: partial or multiple municipal overlaps (SRS REQ-JUR-03).
        ranked = sorted(positive, key=lambda a: positive[a], reverse=True)
        candidates = list(ranked)
        covered = sum(positive.values())
        if covered < 1.0 - self._tolerance:
            candidates.append(self._county_id)
        return RoutingResult(
            status=RoutingStatus.AMBIGUOUS,
            authority_id=None,
            candidates=tuple(candidates),
            disclosure=(
                f"Parcel crosses planning-authority boundary: "
                f"{', '.join(candidates)}; jurisdiction-dependent findings "
                f"withheld pending review (SRS REQ-JUR-03)."
            ),
            evidence=evidence,
        )
