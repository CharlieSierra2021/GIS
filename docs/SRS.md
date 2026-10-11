# Software Requirements Specification — GIS Property Intelligence Platform

**Version:** 1.0 (implementation-ready)
**Applies to:** Volusia County, Florida activation (statewide framework)
**Companion documents:** `docs/SOW.md`, `docs/ICD-FL-001.md`

---

## 1. Introduction

### 1.1 Purpose

This SRS states the normative requirements for the GIS Property Intelligence Platform.
It is the contract between what the system does and what the acceptance suite verifies.
Data-source-level contracts, rights, and launch gates live in `docs/ICD-FL-001.md` and
are incorporated here by reference.

### 1.2 Scope

The Platform resolves a property (address, parcel ID, or geometry), discovers the
authoritative public and licensed datasets for its jurisdiction, fuses them, applies
configurable analysis profiles, and publishes a traceable screening report with explicit
provenance, data vintage, and licensing disclosure on every finding.

### 1.3 Product boundary

The Platform is, and must present itself as, a due-diligence **screening** product.
Every report, API response, template, and UI string SHALL remain inside this boundary:

| It is | It is not |
|---|---|
| A due-diligence screening report (automated, ~2 hr SLA) | A land survey or certified boundary |
| A verified report (manual checks, ~5 business days) | A lending-compliant flood determination |
| Portfolio screening for investors/developers | A wetland delineation or environmental assessment |
| Traceable, versioned, source-cited GIS analysis | A zoning or buildability determination |

Requirements throughout this document implement this boundary; §10 of ICD-FL-001 restates
it at the data-source level. Where a requirement and this boundary conflict, the boundary
wins: the correct behaviour is to report less, or to report uncertainty, never more.

### 1.4 Conventions

- **SHALL** — mandatory, verified by an acceptance or contract test.
- **SHOULD** — expected; deviation requires a documented reason.
- **MAY** — permitted option.
- **null** in any rights or metadata field means *unknown*. Unknown SHALL be treated as
  denied for rights purposes and disclosed (not hidden) for metadata purposes. Never
  fabricate a source date; `unknown` is a valid value.
- **Absence of evidence** — an empty query result or missing layer SHALL NOT be rendered
  as evidence that a condition does not exist. "No wetland record found" never becomes
  "no wetlands."

### 1.5 References

| Document | Role |
|---|---|
| `docs/SOW.md` | Scope, deliverables, phases, exclusions |
| `docs/ICD-FL-001.md` | Volusia connector contracts, rights matrix, launch gates, registry seed |
| `registry/volusia.yaml` | Machine-readable connector registry (generated from ICD §19) |

## 2. Overall description

### 2.1 Operating environment

| Function | Baseline |
|---|---|
| API / orchestration | Python 3.12+, FastAPI |
| Spatial database | PostgreSQL 16 + PostGIS |
| Processing | GDAL, Rasterio, GeoPandas, Shapely |
| Queue | Celery + Redis |
| Object storage | S3-compatible (MinIO in dev) |
| GIS operator env | QGIS |
| Customer maps | Leaflet / OpenLayers |
| Reporting | HTML templates → PDF (WeasyPrint or equivalent) |
| Deployment | Docker Compose, single host |

### 2.2 Actors

- **Customer** — submits properties, resolves ambiguities, receives reports.
- **Reviewer** — resolves human-review queue items created by quality gates.
- **Operator** — maintains registry, connectors, and deployments; runs validation harness.
- **System** — scheduled and event-driven jobs (refresh, drift detection, re-screening).

### 2.3 Design constraints

- C1. **Deny-by-default rights.** Every dataset has separate permissions
  (`discover/query/download/cache/retain_derived/display/report/redistribute`). Any
  `null` permission SHALL be treated as denied.
- C2. **Provenance is a product feature.** Observation date, publication date, and
  retrieval date are distinct facts and SHALL be stored and cited separately.
- C3. **Parcel identity is not geometry.** A geocoded point inside a polygon is
  supporting evidence, not identity. Condo/stacked parcels require unit-level matching.
- C4. **Jurisdiction before conclusions.** Land-use/zoning statements require routing to
  the correct planning authority first.
- C5. **No secrets in the repo.** Credentials live in environment/secrets management;
  `deploy/env.example` documents names only.

## 3. Functional requirements

### 3.1 Intake (REQ-INT)

| ID | Requirement |
|----|-------------|
| REQ-INT-01 | The system SHALL accept a screening request by street address, county parcel ID, or GeoJSON geometry, individually or via portfolio CSV. |
| REQ-INT-02 | The system SHALL validate and normalise intake into a canonical job record before any resolution work begins. |
| REQ-INT-03 | Portfolio CSV intake SHALL process rows independently; one row's failure SHALL NOT block or contaminate others. |
| REQ-INT-04 | The system SHALL assign every job a durable identifier and record all state transitions for audit. |

### 3.2 Parcel resolution (REQ-RES)

| ID | Requirement |
|----|-------------|
| REQ-RES-01 | The system SHALL resolve parcel identity against the county parcel dataset, using address match, parcel-ID match, geometry match, and spatial coincidence as evidence classes — not as interchangeable truth. |
| REQ-RES-02 | A geocoded point falling inside a parcel polygon SHALL be recorded as supporting evidence only and SHALL NOT by itself constitute parcel identity. |
| REQ-RES-03 | When resolution produces multiple plausible candidates, the job SHALL enter `AwaitingCustomerInput` and the customer SHALL be offered the candidates for selection. |
| REQ-RES-04 | The system SHALL NOT break ties by nearest, largest, first, or any other silent heuristic. |
| REQ-RES-05 | Condo and stacked-parcel geographies SHALL be resolved at unit level using unit/situx identifiers; building-level polygons alone are insufficient evidence of unit identity. |
| REQ-RES-06 | The resolution decision SHALL be stored with its evidence set, confidence class, and (where applicable) the customer's selection, for audit and re-screening. |

### 3.3 Jurisdiction routing (REQ-JUR)

| ID | Requirement |
|----|-------------|
| REQ-JUR-01 | The system SHALL determine the parcel's planning authority (unincorporated county vs. named municipality) before producing any land-use or zoning-adjacent finding. |
| REQ-JUR-02 | Planning-authority resolution SHALL consult the authority registry in ICD §3, not inferred from postal city names or geocoder output. |
| REQ-JUR-03 | Where the planning authority cannot be determined, jurisdiction-dependent findings SHALL be omitted with a disclosure, never attributed to the wrong authority. |

### 3.4 Connector orchestration (REQ-CON)

| ID | Requirement |
|----|-------------|
| REQ-CON-01 | Each provider SHALL be accessed through a connector implementing the common contract in ICD §5; provider-specific code SHALL NOT leak into analysis logic. |
| REQ-CON-02 | Connectors SHALL support the access patterns registered for their dataset (ArcGIS REST query, file download, document retrieval, records-request tracking). |
| REQ-CON-03 | Connectors SHALL declare capabilities and limits (pagination, max features, supported CRS) and the orchestrator SHALL respect them. |
| REQ-CON-04 | Connector failures SHALL be classified (unavailable / schema drift / permission denied / empty result) and SHALL degrade per ICD §14 rather than fail the whole job silently. |
| REQ-CON-05 | A validation harness SHALL fetch service metadata, resolve layer IDs, check expected fields/CRS, detect schema drift, and emit a registry-ready fixture record (invoked as `python -m connectors.validate`). |

### 3.5 Source registry and rights (REQ-REG)

| ID | Requirement |
|----|-------------|
| REQ-REG-01 | Every dataset SHALL have a registry record containing authority, vintage, license, freshness policy, and the eight permissions (`discover/query/download/cache/retain_derived/display/report/redistribute`). |
| REQ-REG-02 | Any permission value of `null` SHALL be enforced as denied at query time, display time, and report time — independently. |
| REQ-REG-03 | The system SHALL refuse to display, include in a report, or redistribute any dataset whose corresponding permission is denied or unknown. |
| REQ-REG-04 | Registry changes SHALL be versioned; the registry version used for a job SHALL be recorded in the job's audit trail. |

### 3.6 Storage and provenance (REQ-DAT)

| ID | Requirement |
|----|-------------|
| REQ-DAT-01 | Fetched source data SHALL be stored in PostGIS (vector) and a versioned object store (documents, rasters) as permitted by the dataset's `cache`/`retain_derived` rights. |
| REQ-DAT-02 | Every stored record SHALL carry observation date, publication date, and retrieval date as separate fields, any of which may legitimately be `unknown`. |
| REQ-DAT-03 | Derived geometries SHALL be stored separately from source geometries, tagged with the derivation and registry versions that produced them. |
| REQ-DAT-04 | Every job SHALL have an audit trail sufficient to reconstruct which source version, connector version, registry version, and profile version produced each finding. |

### 3.7 Analysis (REQ-ANL)

| ID | Requirement |
|----|-------------|
| REQ-ANL-01 | The system SHALL implement the `florida_land_screening_v1` profile covering: flood zones, wetlands indicators, hydric soils, subsidence/sinkhole indicators, permit history, contamination sites, future land use, access/frontage, and utility proximity. |
| REQ-ANL-02 | Analysis profiles SHALL be versioned and declaratively configured; a profile change SHALL NOT require connector changes. |
| REQ-ANL-03 | Every finding SHALL carry: the finding, its evidence (dataset + feature + spatial relationship), source citations, and the three provenance dates where known. |
| REQ-ANL-04 | Findings SHALL be phrased as screening indicators per §1.3. Language implying certification, determination, or delineation is a defect. |
| REQ-ANL-05 | Absent layers, empty results, and denied permissions SHALL produce explicit "not assessed / data unavailable" findings — never silent omission and never a negative claim. |

### 3.8 Quality gates (REQ-QG)

| ID | Requirement |
|----|-------------|
| REQ-QG-01 | Before publication, every job SHALL pass through gates for freshness, coverage, conflict, and license as defined in ICD §15. |
| REQ-QG-02 | Gate outcomes SHALL select one of four dispositions: auto-publish, qualified output (published with disclosed qualifications), human review, or blocked. |
| REQ-QG-03 | Auto-publish SHALL occur only when parcel identity, licensing, deliverable rights, and all mandatory gates pass. |
| REQ-QG-04 | Every gate decision SHALL be logged with inputs and outcome; human-review resolutions SHALL record reviewer and rationale. |

### 3.9 Reporting (REQ-RPT)

| ID | Requirement |
|----|-------------|
| REQ-RPT-01 | The system SHALL produce a screening report (HTML template → PDF) containing every finding with its source citation, vintage, and license disclosure. |
| REQ-RPT-02 | The report SHALL display the product-boundary statement (§1.3) and the per-dataset licensing disclosures applicable to its content. |
| REQ-RPT-03 | A report manifest SHALL record registry/profile/template versions and the gate disposition under which the report was published. |
| REQ-RPT-04 | Content for which `display` or `report` rights are denied SHALL NOT appear in any report; the imagery-denied degradation path (ICD §14) SHALL render a functional report without imagery. |

### 3.10 Customer portal (REQ-PTL)

| ID | Requirement |
|----|-------------|
| REQ-PTL-01 | The portal SHALL display job status, resolved parcel, findings, and report download, using Leaflet/OpenLayers maps. |
| REQ-PTL-02 | The portal SHALL present resolution candidates for `AwaitingCustomerInput` jobs and record the customer's selection. |
| REQ-PTL-03 | Map layers in the portal SHALL be filtered by `display` rights at render time, not merely hidden in the UI. |

## 4. Non-functional requirements

### 4.1 Performance (REQ-PERF)

| ID | Requirement |
|----|-------------|
| REQ-PERF-01 | An automated screening job SHALL reach a publishable or blocked state within 2 hours of intake under normal source availability. |
| REQ-PERF-02 | A verified report (human review path) SHALL be delivered within 5 business days. |
| REQ-PERF-03 | Records-request dependencies SHALL be surfaced as pending with disclosed expected timelines rather than counting against the 2-hour SLA. |

### 4.2 Security (REQ-SEC)

| ID | Requirement |
|----|-------------|
| REQ-SEC-01 | No secrets SHALL be committed to the repository; `deploy/env.example` documents variable names only. |
| REQ-SEC-02 | Source-system credentials SHALL be scoped per connector and stored in the secrets manager. |
| REQ-SEC-03 | Customer data SHALL be isolated per account; one customer's job SHALL NOT expose another's data or findings. |

### 4.3 Auditability and reliability (REQ-AUD)

| ID | Requirement |
|----|-------------|
| REQ-AUD-01 | It SHALL be possible to regenerate any published report's evidence set from the audit trail and versioned stores. |
| REQ-AUD-02 | Schema drift detected by contract tests SHALL quarantine the affected connector's output until reviewed (ICD §17). |
| REQ-AUD-03 | The system SHALL tolerate individual source outages; degraded findings are disclosed per REQ-ANL-05. |

## 5. Verification plan

Requirements are verified by three mechanisms: **contract tests** (`tests/connectors/`,
per-source fixtures and schema drift), **validation set** (`tests/resolution/`, labelled
parcel-match cases), and the **acceptance suite** (`tests/acceptance/`, FL-TST-*) defined
in ICD §16.

| Requirement group | Primary verification |
|---|---|
| REQ-INT | FL-TST-01, unit tests |
| REQ-RES | FL-TST-02/03/04 + labelled validation set |
| REQ-JUR | FL-TST-04 |
| REQ-CON | FL-TST-05 + connector contract tests |
| REQ-REG | FL-TST-11 + rights-matrix unit tests |
| REQ-DAT | FL-TST-12 (audit reconstruction) |
| REQ-ANL | FL-TST-06 through FL-TST-10 |
| REQ-QG | FL-TST-11 |
| REQ-RPT | FL-TST-13 |
| REQ-PTL | FL-TST-14 |
| REQ-PERF/SEC/AUD | FL-TST-15 + deployment review |

No requirement is accepted on inspection alone; every SHALL maps to at least one test or
gate in ICD §16.

### 5.1 Installed-package deployment regression (M14)

`tests/api/test_health.py::test_installed_wheel_starts_outside_checkout` builds a
non-editable wheel, checks the profile and report/portal template resources, installs
into a temporary target, and exercises API health and portal rendering outside the
source tree. The registry is supplied explicitly using `PI_REGISTRY_PATH`.

`tests/connectors/test_registry.py` verifies configuration precedence and refusal to
fall back when the configured registry is missing. No rights values are changed by
this milestone. The Dockerfile supplies the registry path and copies migrations, but
Docker/Compose execution and PostgreSQL migration acceptance remain separate gates.
