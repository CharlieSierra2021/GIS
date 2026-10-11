"""Screening engine — SRS REQ-ANL-01..05, ICD §14 degradation paths.

Runs a profile against an EvidenceFetcher. Every failure degrades to a
disclosed NOT_ASSESSED finding; empty pages become NOT_FOUND ("no record
found", never "absent"); registry rights are re-checked here so the engine
does not depend on the connector to enforce REQ-REG-02.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from analysis.analyzers import ANALYZERS
from analysis.findings import (
    Finding,
    FindingStatus,
    ScreeningResult,
    SourceCitation,
    not_assessed,
    not_found,
)
from analysis.profile import Profile
from connectors.contract import ConnectorError, FeaturePage
from connectors.registry import Registry


class EvidenceFetcher(Protocol):
    def fetch(
        self,
        dataset_id: str,
        parcel_wkt: str,
        spatial_rel: str,
        buffer_m: float | None,
        authority_id: str | None = None,
    ) -> FeaturePage:
        """Fetch features for one dataset; raises ConnectorError on failure."""
        ...


class ScreeningContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    job_id: str
    parcel_id: str
    parcel_wkt: str
    registry: Registry
    authority_id: str | None = None
    now: datetime


def screen(ctx: ScreeningContext, profile: Profile, fetcher: EvidenceFetcher) -> ScreeningResult:
    findings: list[Finding] = []
    for area, spec in profile.areas.items():
        fid = f"{ctx.job_id}:{area}"

        if spec.jurisdiction_dependent and ctx.authority_id is None:
            findings.append(
                not_assessed(
                    fid,
                    area,
                    reason=(
                        "planning authority unresolved; jurisdiction-dependent "
                        "findings withheld (SRS REQ-JUR-03)"
                    ),
                    mandatory=spec.mandatory,
                    dataset_id=spec.dataset,
                )
            )
            continue

        ds_id = spec.dataset
        authority_name = None
        if spec.jurisdiction_dependent and ctx.authority_id:
            authority = ctx.registry.authority(ctx.authority_id)
            authority_name = authority.name
            if authority.type == "municipal":
                ds_id = "mun_flu"

        try:
            dataset = ctx.registry.dataset(ds_id)
        except KeyError:
            findings.append(
                not_assessed(
                    fid, area, reason=f"dataset {ds_id} not in registry",
                    mandatory=spec.mandatory, dataset_id=ds_id,
                )
            )
            continue

        if not dataset.permissions.allows("query"):
            findings.append(
                not_assessed(
                    fid,
                    area,
                    reason=f"registry denies query for {ds_id}",
                    mandatory=spec.mandatory,
                    dataset_id=ds_id,
                )
            )
            continue

        try:
            page = fetcher.fetch(
                ds_id,
                ctx.parcel_wkt,
                spec.spatial_rel,
                spec.buffer_m,
                ctx.authority_id if spec.jurisdiction_dependent else None,
            )
        except ConnectorError as exc:
            reason = f"{exc.failure_class}: {exc.detail}"
            if ds_id == "mun_flu":
                reason = (
                    f"municipal FLU unavailable — authority: {authority_name}"
                )
            findings.append(
                not_assessed(
                    fid, area, reason=reason,
                    mandatory=spec.mandatory, dataset_id=ds_id,
                )
            )
            continue

        if not page.features:
            vintage = dataset.vintage
            findings.append(
                not_found(
                    fid,
                    area,
                    dataset_id=ds_id,
                    provider_id=dataset.provider,
                    registry_version=ctx.registry.registry_version,
                    retrieved_at=ctx.now,
                    mandatory=spec.mandatory,
                    observation_date=vintage.observation if vintage else None,
                    publication_date=vintage.publication if vintage else None,
                    license_name=dataset.license.name,
                    license_gate=dataset.license.gate,
                )
            )
            continue

        analyzer = ANALYZERS[spec.analyzer]
        effective_spec = spec.model_copy(update={"dataset": ds_id})
        statement, evidence, disclosure = analyzer(
            area, effective_spec, page.features, ctx
        )
        if ds_id != spec.dataset:
            evidence["dataset_id"] = ds_id
        prov = page.features[0].provenance
        findings.append(
            Finding(
                id=fid,
                area=area,
                status=FindingStatus.PRESENT,
                statement=statement,
                evidence=evidence,
                citation=SourceCitation(
                    dataset_id=ds_id,
                    provider_id=dataset.provider,
                    feature_keys=[f.key for f in page.features],
                    observation_date=prov.observation_date,
                    publication_date=prov.publication_date,
                    retrieved_at=prov.retrieved_at,
                    registry_version=ctx.registry.registry_version,
                    license_name=dataset.license.name,
                    license_gate=dataset.license.gate,
                ),
                disclosure=disclosure,
                mandatory=spec.mandatory,
            )
        )

    return ScreeningResult(
        job_id=ctx.job_id,
        parcel_id=ctx.parcel_id,
        profile=profile.profile,
        profile_version=profile.version,
        registry_version=ctx.registry.registry_version,
        findings=findings,
        produced_at=ctx.now,
    )
