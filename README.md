# GIS Property Intelligence Platform

Automated, drone-free property due-diligence and land-intelligence service. The platform resolves a
property (address, parcel ID, or geometry), discovers the authoritative public and licensed datasets
for its jurisdiction, fuses them, applies configurable analysis profiles, and publishes a traceable
screening report — with explicit provenance, data vintage, and licensing disclosure on every finding.

**Launch geography:** Volusia County, Florida
**Architecture:** statewide connector framework, activated county by county
**Current phase:** ICD-FL-001 implementation-ready, rights-pending

## What this product is — and is not

| It is | It is not |
|---|---|
| A due-diligence screening report (automated, ~2 hr SLA) | A land survey or certified boundary |
| A verified report (manual checks, ~5 business days) | A lending-compliant flood determination |
| Portfolio screening for investors/developers | A wetland delineation or environmental assessment |
| Traceable, versioned, source-cited GIS analysis | A zoning or buildability determination |

Every report must remain honest about this boundary. See `docs/SRS.md` §1.3 and `docs/ICD-FL-001.md` §10.

## Architecture

```text
Customer intake (address / parcel / geometry / portfolio CSV)
        │
        ▼
Parcel resolution ── ambiguity ──► AwaitingCustomerInput
        │                               (customer selects candidate)
        ▼
Jurisdiction router ──► municipal vs. county planning authority
        ▼
Connector orchestration ──► ArcGIS REST / downloads / documents / records requests
        │
        ▼
Source registry (authority · vintage · license · freshness · permissions)
        │
        ▼
PostGIS + versioned object store + audit trail
        │
        ▼
Florida screening engine (flood · wetlands · hydric soils · subsidence ·
                        permits · contamination · land use · access · utilities)
        │
        ▼
Quality gates ──► auto-publish | qualified output | human review | blocked
        │
        ▼
Report publisher + customer portal (Leaflet/OpenLayers)
```

## Tech stack

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
| Deployment | Docker Compose (single host) |

## Repository layout

```text
property-intel/
├── README.md                  ← you are here
├── docs/
│   ├── SOW.md                 ← statement of work: scope, deliverables, phases
│   ├── SRS.md                 ← system requirements (normative SHALL statements)
│   └── ICD-FL-001.md          ← Volusia County data-source interface control doc
├── registry/
│   └── volusia.yaml           ← connector registry seed (see ICD §19)
├── src/
│   ├── api/                   ← FastAPI app: jobs, portfolios, files, review
│   ├── connectors/            ← one adapter per provider; common contract
│   ├── resolution/            ← parcel identity + condo/stacked-parcel logic
│   ├── jurisdiction/          ← municipal routing + authority registry
│   ├── analysis/              ← analysis profiles (florida_land_screening_v1, …)
│   ├── quality/               ← freshness, coverage, conflict, license gates
│   ├── reports/               ← templates, manifest, PDF rendering
│   └── workers/               ← Celery tasks (see ICD §8 task types)
├── tests/
│   ├── connectors/            ← per-source fixtures + schema-drift tests
│   ├── resolution/            ← labelled parcel-match validation set
│   └── acceptance/            ← FL-TST-* acceptance suite
└── deploy/
    ├── docker-compose.yml
    └── env.example            ← NO secrets in the repo
```

## Getting started (development)

```bash
cp deploy/env.example .env        # fill in local values; secrets go to a secrets manager
docker compose -f deploy/docker-compose.yml up -d   # postgis, redis, minio, api, worker
docker compose exec api alembic upgrade head        # schema migrations
pytest                            # unit + connector contract tests
pytest tests/acceptance           # FL-TST acceptance suite (requires fixtures)
```

Connector validation harness (verify a live service before registering it):

```bash
python -m connectors.validate --provider volusia_county_gis --dataset basemap_parcels
```

The harness fetches service metadata, resolves layer IDs, checks expected fields/CRS,
detects schema drift, and writes a registry-ready fixture record.

## Core concepts you must respect

1. **Deny-by-default rights.** Every dataset has separate permissions
   (`discover/query/download/cache/retain_derived/display/report/redistribute`).
   `null` means *unknown*, not *allowed*. Public availability ≠ commercial license.
2. **Provenance is a product feature.** Observation date, publication date, and
   retrieval date are different facts. Never fabricate a source date; `unknown` is a valid value.
3. **Parcel identity is not geometry.** A geocoded point inside a polygon is supporting
   evidence, not identity. Condos/stacked parcels require unit-level matching — never
   pick nearest/largest/first as a tie-breaker.
4. **Absence of evidence ≠ evidence of absence.** "No wetland record found" never
   becomes "no wetlands." Empty layers are not proof of anything.
5. **Quality gates block publication.** Auto-publish only when parcel identity,
   licensing, deliverable rights, and mandatory quality gates all pass.
6. **Jurisdiction before conclusions.** Zoning/FLU statements require routing the
   parcel to the correct planning authority (county vs. municipality) first.

## Document index

| Document | Purpose |
|---|---|
| [`docs/SOW.md`](docs/SOW.md) | Scope, deliverables, phases, acceptance, exclusions |
| [`docs/SRS.md`](docs/SRS.md) | Normative system requirements + verification plan |
| [`docs/ICD-FL-001.md`](docs/ICD-FL-001.md) | Volusia connector contracts, rights, tests, freeze criteria |

## Launch status

Before any customer-facing release, the launch gates **L1–L9** (`docs/ICD-FL-001.md` §12)
must close — most are procurement/legal verifications, not engineering. Highest-risk item:
report/display rights on county orthoimagery (2024 service was processed by a commercial
vendor; rights are not implied by public availability). The imagery-denied degradation
path must be demonstrated end-to-end before freeze.
