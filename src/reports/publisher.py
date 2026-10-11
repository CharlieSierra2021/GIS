"""Report publisher — SRS REQ-RPT-01..04, ICD §10/§11/§14.

Renders the screening report (HTML via Jinja2, autoescape on), applies the
rights filter as defence-in-depth, and produces the manifest. PDF output is
deferred: ``PdfRenderer`` is a protocol and the default ``NullPdfRenderer``
records "pdf renderer not configured" in the manifest. WeasyPrint (or
equivalent) lands as a deploy-time dependency — the HTML rendered here is
its input.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from analysis.findings import Finding
from connectors.registry import Registry
from quality.gates import Disposition
from reports.manifest import BOUNDARY_STATEMENT, LicenseDisclosure, ReportManifest
from workers.jobs import Job

_DEFAULT_TEMPLATES = Path(__file__).parent / "templates"
_AREA_ORDER = (
    "flood",
    "wetlands",
    "hydric_soils",
    "subsidence",
    "permits",
    "contamination",
    "land_use",
    "access",
    "utilities",
)


class PdfRenderer(Protocol):
    def render(self, html: str) -> dict: ...


class NullPdfRenderer:
    def render(self, html: str) -> dict:
        return {
            "renderer": "none",
            "path": None,
            "note": "pdf renderer not configured",
        }


class PublishedReport(BaseModel):
    manifest: ReportManifest
    html: str


class RightsFilter:
    """Defence-in-depth rights enforcement at render time (REQ-RPT-04).

    The quality gates already BLOCK publication on denied rights, so in a
    normal flow nothing is removed — this exists so a mistakenly-published
    job still cannot leak denied content.
    """

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def filter_findings(
        self, findings: list[Finding]
    ) -> tuple[list[Finding], list[str]]:
        kept: list[Finding] = []
        excluded: list[str] = []
        for finding in findings:
            ds = (
                self._registry.dataset(finding.citation.dataset_id)
                if finding.citation
                else None
            )
            if ds and not ds.permissions.allows("report"):
                excluded.append(
                    f"finding {finding.id} withheld: {ds.id} report right "
                    f"denied/unknown"
                )
                continue
            if (
                ds
                and finding.evidence.get("geometry_wkt")
                and not ds.permissions.allows("display")
            ):
                excluded.append(
                    f"geometry for {ds.id} not displayed: display right "
                    f"denied/unknown"
                )
                evidence = dict(finding.evidence)
                evidence.pop("geometry_wkt")
                finding = finding.model_copy(update={"evidence": evidence})
            kept.append(finding)
        return kept, excluded

    def imagery_mode(self) -> str:
        perms = self._registry.dataset("ortho_2024").permissions
        if perms.allows("display") and perms.allows("report"):
            return "licensed"
        return "denied"

    def map_layers(self, findings: list[Finding]) -> list[str]:
        layers = []
        for finding in findings:
            if not finding.citation or not finding.evidence.get("geometry_wkt"):
                continue
            ds = self._registry.dataset(finding.citation.dataset_id)
            if ds.permissions.allows("display") and ds.id not in layers:
                layers.append(ds.id)
        return layers


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReportPublisher:
    def __init__(
        self,
        registry: Registry,
        templates_dir: Path | None = None,
        pdf: PdfRenderer | None = None,
        template_version: str = "1.0.0",
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._registry = registry
        self._pdf = pdf or NullPdfRenderer()
        self._template_version = template_version
        self._clock = clock
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir or _DEFAULT_TEMPLATES)),
            autoescape=select_autoescape(default=True),
        )

    def publish(self, job: Job) -> PublishedReport:
        if job.gates is None or job.gates.disposition not in (
            Disposition.AUTO_PUBLISH,
            Disposition.QUALIFIED_OUTPUT,
        ):
            raise ValueError(
                f"cannot publish disposition "
                f"{job.gates.disposition if job.gates else None}"
            )

        rights = RightsFilter(self._registry)
        findings, excluded = rights.filter_findings(
            job.screening.findings if job.screening else []
        )
        imagery = rights.imagery_mode()
        layers = rights.map_layers(findings)
        disclosures = self._disclosures(findings)

        # Authority name for the jurisdiction section.
        routing = job.routing or {}
        authority_name = None
        if routing.get("authority_id"):
            authority_name = self._registry.authority(
                routing["authority_id"]
            ).name

        groups = self._group(findings)
        template = self._env.get_template("report.html.j2")
        generated_at = self._clock()
        html = template.render(
            job=job,
            finding_groups=groups,
            disclosures=disclosures,
            boundary_statement=BOUNDARY_STATEMENT,
            imagery=imagery,
            map_layers=layers,
            qualifications=job.gates.qualifications,
            excluded=excluded,
            routing=routing,
            authority_name=authority_name,
            generated_at=generated_at,
        )

        manifest = ReportManifest(
            job_id=job.id,
            account_id=job.account_id,
            parcel_id=job.resolution.parcel_id if job.resolution else None,
            generated_at=generated_at,
            registry_version=job.registry_version,
            profile=job.profile,
            profile_version=job.profile_version,
            template_version=self._template_version,
            disposition=job.gates.disposition,
            qualifications=list(job.gates.qualifications),
            gate_results=list(job.gates.gates),
            disclosures=disclosures,
            imagery=imagery,
            map_layers=layers,
            excluded_content=excluded,
            boundary_statement=BOUNDARY_STATEMENT,
            pdf=self._pdf.render(html),
            html_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
        )
        return PublishedReport(manifest=manifest, html=html)

    def _group(self, findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
        groups: dict[str, list[Finding]] = {}
        for f in findings:
            groups.setdefault(f.area, []).append(f)
        return [
            (area, groups[area]) for area in _AREA_ORDER if area in groups
        ] + [
            (area, fs)
            for area, fs in groups.items()
            if area not in _AREA_ORDER
        ]

    def _disclosures(self, findings: list[Finding]) -> list[LicenseDisclosure]:
        seen: dict[str, LicenseDisclosure] = {}
        for finding in findings:
            if not finding.citation:
                continue
            ds_id = finding.citation.dataset_id
            if ds_id in seen:
                continue
            ds = self._registry.dataset(ds_id)
            seen[ds_id] = self._disclosure(ds, finding.citation.retrieved_at)
        # Imagery licence status is always disclosed (ICD §14 first row).
        if "ortho_2024" not in seen:
            seen["ortho_2024"] = self._disclosure(
                self._registry.dataset("ortho_2024"), None
            )
        return list(seen.values())

    def _disclosure(self, ds, retrieved_at) -> LicenseDisclosure:
        try:
            provider_name = self._registry.provider(ds.provider).name
        except KeyError:
            provider_name = None
        return LicenseDisclosure(
            dataset_id=ds.id,
            provider_name=provider_name,
            license_name=ds.license.name,
            gate=ds.license.gate,
            display_allowed=ds.permissions.allows("display"),
            report_allowed=ds.permissions.allows("report"),
            vintage_observation=ds.vintage.observation if ds.vintage else None,
            vintage_publication=ds.vintage.publication if ds.vintage else None,
            retrieved_at=retrieved_at,
        )
