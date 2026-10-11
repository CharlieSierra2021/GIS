# ICD-FL-001 — Volusia County Data-Source Interface Control Document

**Interface control document for:** Florida activation FL-001, Volusia County
**Status:** Implementation-ready, rights-pending
**Companion documents:** `docs/SRS.md`, `docs/SOW.md`, `registry/volusia.yaml`

---

## 1. Purpose and scope

### 1.1 Purpose

This ICD defines the contracts between the Platform and every external data source used
in the Volusia County activation: what each source is, how it is accessed, what rights
the Platform holds in it, how its failures degrade, and what must be verified before the
activation may freeze.

### 1.2 Activation scope

This document covers the Volusia County activation only. The connector framework is
statewide; other counties are activated by their own ICDs on the same framework. Dataset
IDs, task types, and gate definitions here are the reference implementation for future
county ICDs.

### 1.3 Status convention

Every dataset in this document carries one of three statuses:

- `registered` — contract defined, connector implemented or implementable, rights confirmed
- `implementation-ready` — contract defined; connector work may proceed; rights pending
- `denied` — a required permission is refused or withdrawn; the deny-path applies

As of this revision, the activation is **implementation-ready, rights-pending**: no
dataset is `registered` until its launch gate in §12 closes.

## 2. Referenced documents and terminology

| Reference | Role |
|---|---|
| `docs/SRS.md` | Normative system behaviour; §1.3 defines the product boundary |
| `docs/SOW.md` | Scope, phases, deliverables, acceptance |
| `registry/volusia.yaml` | Machine-readable seed generated from §19 of this document |

Terminology follows SRS §1.4: `null` means unknown and is treated as denied for rights
and disclosed for metadata; absence of evidence is never evidence of absence.

## 3. Jurisdiction profile and planning authorities

Volusia County contains 16 incorporated municipalities plus unincorporated territory.
Land-use and future-land-use statements must be attributed to the correct planning
authority (SRS REQ-JUR). The authority registry below is normative; it is resolved by
parcel situs, never by postal city name or geocoder output.

| Authority ID | Planning authority | Type |
|---|---|---|
| `volusia_uninc` | Volusia County (unincorporated) | County |
| `daytona_beach` | City of Daytona Beach | Municipal |
| `daytona_beach_shores` | City of Daytona Beach Shores | Municipal |
| `debary` | City of DeBary | Municipal |
| `deland` | City of DeLand | Municipal (county seat) |
| `deltona` | City of Deltona | Municipal |
| `edgewater` | City of Edgewater | Municipal |
| `flagler_beach` | City of Flagler Beach (partial) | Municipal |
| `holly_hill` | City of Holly Hill | Municipal |
| `lake_helen` | City of Lake Helen | Municipal |
| `new_smyrna_beach` | City of New Smyrna Beach | Municipal |
| `oak_hill` | City of Oak Hill | Municipal |
| `orange_city` | City of Orange City | Municipal |
| `ormond_beach` | City of Ormond Beach | Municipal |
| `pierson` | Town of Pierson | Municipal |
| `ponce_inlet` | Town of Ponce Inlet | Municipal |
| `port_orange` | City of Port Orange | Municipal |
| `south_daytona` | City of South Daytona | Municipal |

Boundary determination uses the county municipal-boundary layer (`mun_boundaries`,
§6). Parcels crossing a boundary, or in disputed/annexation-pending areas, produce a
disclosed ambiguity, not a guessed attribution.

## 4. Provider inventory

| Provider ID | Provider | Role in screening |
|---|---|---|
| `volusia_county_gis` | Volusia County GIS (ArcGIS REST) | Parcels, municipal boundaries, FLU, orthoimagery |
| `volusia_pa` | Volusia County Property Appraiser | CAMA characteristics, situs addresses, ownership |
| `volusia_clerk` | Volusia County Clerk of Court | Official records (deeds, plats) — records-request path |
| `volusia_permits` | County/municipal permitting systems | Permit history signal |
| `fema_nfhl` | FEMA National Flood Hazard Layer | Flood zones (SFHA, zone class) |
| `usfws_nwi` | USFWS National Wetlands Inventory | Wetland indicators |
| `usda_nrcs` | USDA NRCS soils (SSURGO/gSSURGO) | Hydric soils, drainage class |
| `fgs` | Florida Geological Survey | Subsidence/sinkhole incident reports |
| `fdep` | Florida DEP | Contamination sites, tanks, brownfields, cleanup status |
| `sjrwmd` | St. Johns River Water Management District | District land use, water-resource context |
| `fdot` | Florida DOT | Road/access context, right-of-way |

## 5. Connector contract

Every provider connector SHALL implement this contract. Provider-specific behaviour is
confined to the adapter; analysis code consumes the contract only.

### 5.1 Interface

```
Connector
  describe()   -> ServiceDescriptor   # metadata, layer IDs, fields, CRS, limits
  capabilities() -> Capabilities      # pagination, max_features, query types, CRS list
  query(req)   -> FeaturePage         # spatial/attribute query, paged
  download(req) -> ObjectRef          # bulk artefact to versioned object store
  documents(req) -> DocumentRef[]     # document retrieval where applicable
  health()     -> HealthStatus        # liveness + metadata fingerprint
```

### 5.2 Requirements

- CON-A. `describe()` SHALL return live service metadata (not cached) for drift checks.
- CON-B. Every returned feature SHALL carry source dataset ID, source feature key,
  retrieval timestamp, and native CRS; reprojection to the working CRS (EPSG:4326
  storage / EPSG:3087 Florida GDL Albers for measurement) happens at ingest.
- CON-C. Connectors SHALL NOT retry indefinitely: bounded retries with backoff, then a
  classified failure (§5.3).
- CON-D. Connectors SHALL NOT fabricate missing metadata; absent fields are `null`.
- CON-E. Access patterns are per-dataset, registered in §6: `arcgis_query`,
  `file_download`, `document_retrieval`, `records_request`.

### 5.3 Failure taxonomy

| Class | Meaning | Job effect |
|---|---|---|
| `source_unavailable` | Timeout, 5xx, DNS | Degrade per §14; retry on schedule |
| `schema_drift` | Metadata fingerprint mismatch | Quarantine connector output per §17 |
| `permission_denied` | Auth/licence refusal at source | Block affected finding; disclose |
| `empty_result` | Successful query, zero features | "Not assessed / no record" per SRS REQ-ANL-05 |

## 6. Dataset and endpoint catalog

Concrete service URLs and layer IDs are recorded in `registry/volusia.yaml` (generated
per §19) and verified by the validation harness — not duplicated here, so this document
stays stable when endpoints move. Access types per §5.2-E.

| Dataset ID | Provider | Contents | Access | Status |
|---|---|---|---|---|
| `basemap_parcels` | `volusia_county_gis` | Parcel polygons, parcel ID, situs | `arcgis_query` | implementation-ready |
| `mun_boundaries` | `volusia_county_gis` | Municipal boundary polygons | `arcgis_query` | implementation-ready |
| `county_flu` | `volusia_county_gis` | County future land use (unincorporated) | `arcgis_query` | implementation-ready |
| `mun_flu_<authority_id>` | municipal GIS / county host | Municipal FLU, per §3 authority | `arcgis_query` | implementation-ready |
| `ortho_2024` | `volusia_county_gis` | 2024 orthoimagery service | `arcgis_query` (tile/WMS) | implementation-ready — **rights pending** |
| `cama` | `volusia_pa` | Parcel characteristics, buildings, sales | `file_download` / `arcgis_query` | implementation-ready |
| `official_records` | `volusia_clerk` | Deeds, plats, recorded docs | `records_request` | implementation-ready |
| `permits` | `volusia_permits` | Permit history by parcel | `arcgis_query` / `document_retrieval` | implementation-ready |
| `nfhl_flood` | `fema_nfhl` | SFHA, flood zone class, BFE where mapped | `file_download` / `arcgis_query` | implementation-ready |
| `nwi_wetlands` | `usfws_nwi` | NWI wetland polygons + attributes | `file_download` / `arcgis_query` | implementation-ready |
| `ssurgo_soils` | `usda_nrcs` | Hydric rating, drainage class, map units | `file_download` | implementation-ready |
| `sinkhole_reports` | `fgs` | Subsidence incident reports | `file_download` | implementation-ready |
| `fdep_contam` | `fdep` | Cleanup sites, tanks, brownfields | `arcgis_query` / `file_download` | implementation-ready |
| `sjrwmd_landuse` | `sjrwmd` | District land-use/land-cover | `file_download` | implementation-ready |
| `fdot_roads` | `fdot` | Road network, functional class, ROW | `file_download` | implementation-ready |
| `utility_service` | `volusia_county_gis` / municipal utilities | Water/wastewater service areas, proximity signal | `arcgis_query` | implementation-ready |

## 7. Authentication and access modes

| Mode | Applies to | Handling |
|---|---|---|
| Public anonymous | Federal layers, county read services | No credential; still rights-gated for `display`/`report` |
| Registered/licensed | CAMA extracts, imagery where licensed | Credential in secrets manager; licence terms in registry `license` field |
| Records request | Clerk official records, some permit docs | Tracked request workflow; findings report `pending` with disclosed timeline |

Public availability is not a licence. Every entry above is rights-gated by §11 regardless
of authentication mode.

## 8. Task types

Celery task catalogue (`src/workers/`). Task names are normative; payload schemas live
with the code.

| Task type | Purpose | Retries |
|---|---|---|
| `resolve_parcel` | REQ-RES resolution; may suspend job to `AwaitingCustomerInput` | n/a |
| `route_jurisdiction` | Planning-authority resolution per §3 | n/a |
| `fetch_source` | Generic connector fetch; parameterised by `(provider_id, dataset_id)` | bounded, §5.3 |
| `fetch_parcels` / `fetch_fema_flood` / `fetch_nwi` / `fetch_soils` / `fetch_permits` / `fetch_contamination` / `fetch_landuse` / `fetch_ortho` | Typed wrappers over `fetch_source` for readable queues and per-dataset metrics | bounded |
| `screen_profile` | Run `florida_land_screening_v1` over fetched evidence | none (idempotent, re-runnable) |
| `quality_gates` | Evaluate §15 gates; set disposition | none |
| `publish_report` | Render + store report and manifest | bounded |
| `refresh_source` | Scheduled re-fetch per registry `freshness` policy | bounded |
| `drift_check` | Periodic `describe()` fingerprint vs. registry | bounded |
| `registry_sync` | Apply reviewed registry amendments; bump registry version | none |

`AwaitingCustomerInput` is a job state, not a task: `resolve_parcel` returns it and the
job resumes on customer selection (SRS REQ-RES-03).

## 9. Schema and field mapping conventions

- Each dataset registers expected fields (name, type, nullability) in the registry;
  the contract test compares them against live `describe()` output.
- Parcel key: county parcel ID is the join key across county datasets; federal layers
  join spatially and never by name inference.
- All storage geometries: EPSG:4326; area/length measurement: EPSG:3087. Native CRS is
  preserved in provenance.
- Field mappings are versioned with the registry; a mapping change bumps the registry
  version and invalidates cached derived features for that dataset.

## 10. Product boundary

Restating SRS §1.3 at the data level. Reports produced under this ICD:

| May state | May not state or imply |
|---|---|
| "Parcel intersects FEMA zone AE per NFHL panel … dated …" | "Flood determination" or lender-usable certification |
| "NWI maps palustrine wetland on the parcel" | "Wetlands present/absent" as a delineated fact |
| "NRCS map unit … is rated hydric" | "On-site soils are …" |
| "No FDEP cleanup site within 0.25 mi as retrieved …" | "The site is clean" |
| "County FLU designates … per … comprehensive plan" | "Zoning permits …" or buildability conclusions |
| "Orthophoto (2024) shows …" | Any planimetric boundary claim |

A finding that cannot be phrased inside the left column is removed or re-phrased; this
is a report-template review item in §16 (FL-TST-13).

## 11. Rights and licensing matrix

Permissions per dataset, per SRS REQ-REG. `null` = unknown = denied. This matrix is the
normative copy; `registry/volusia.yaml` is generated from it.

| Dataset | discover | query | download | cache | retain_derived | display | report | redistribute |
|---|---|---|---|---|---|---|---|---|
| `basemap_parcels` | ✓ | ✓ | ✓ | null | null | null | null | ✗ |
| `mun_boundaries` | ✓ | ✓ | ✓ | null | null | null | null | ✗ |
| `county_flu` / `mun_flu_*` | ✓ | ✓ | ✓ | null | null | null | null | ✗ |
| `ortho_2024` | ✓ | ✓ | null | null | null | **null — see below** | **null — see below** | ✗ |
| `cama` | ✓ | ✓ | null | null | null | n/a | null | ✗ |
| `official_records` | ✓ | null | null | null | null | null | null | ✗ |
| `permits` | ✓ | null | null | null | null | null | null | ✗ |
| `nfhl_flood` | ✓ | ✓ | ✓ | ✓ | null | ✓ | null | ✗ |
| `nwi_wetlands` | ✓ | ✓ | ✓ | ✓ | null | ✓ | null | ✗ |
| `ssurgo_soils` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | null | ✗ |
| `sinkhole_reports` | ✓ | ✓ | ✓ | ✓ | null | ✓ | null | ✗ |
| `fdep_contam` | ✓ | ✓ | ✓ | ✓ | null | ✓ | null | ✗ |
| `sjrwmd_landuse` | ✓ | ✓ | ✓ | ✓ | null | ✓ | null | ✗ |
| `fdot_roads` | ✓ | ✓ | ✓ | ✓ | null | ✓ | null | ✗ |
| `utility_service` | ✓ | null | null | null | null | null | null | ✗ |

**Orthoimagery risk (highest-risk launch item).** The 2024 ortho service was processed
by a commercial vendor. Public tile access does **not** imply display/report rights for
commercial reports. Until L2 closes, `display` and `report` are `null` (denied) and the
imagery-denied degradation path (§14) is the default rendering mode.

`redistribute` is denied for every dataset by default and may only be set ✓ with an
explicit licence clause cited in the registry `license` field.

## 12. Launch gates L1–L9

Binary gates. "Partially licensed" is not a pass. Most gates are procurement/legal
verifications, not engineering.

| Gate | Criterion | Owner type |
|---|---|---|
| L1 | Parcel + CAMA `report`/`display` rights confirmed in writing (county GIS / PA terms or licence) | Procurement/legal |
| L2 | Orthoimagery `display`/`report` rights confirmed, **or** imagery-denied path accepted as launch configuration and demonstrated end-to-end | Procurement/legal + engineering |
| L3 | FEMA NFHL use and citation terms confirmed | Legal |
| L4 | USFWS NWI display terms confirmed | Legal |
| L5 | NRCS soils display terms confirmed | Legal |
| L6 | FDEP, FGS, SJRWMD, FDOT data terms confirmed | Legal |
| L7 | Records-request workflows live for clerk/permit documents, with disclosed SLAs | Ops |
| L8 | Customer-facing disclaimers and ToS approved by counsel against §10 boundary | Legal |
| L9 | E&O / professional-liability review complete for screening-product claims | Legal/finance |

Rights cells in §11 are updated only with a gate citation (e.g., `report: ✓ (L2)`).

## 13. Provenance and vintage requirements

- Every finding carries observation date (data's effective date), publication date
  (source release), and retrieval date (our fetch) independently; `unknown` is valid
  and disclosed.
- Federal vintages (e.g., NFHL panel effective date, NWI photo year, SSURGO survey
  vintage) are captured at ingest and rendered verbatim — never recomputed or guessed.
- Freshness policies per dataset are in the registry; `refresh_source` enforces them
  and stale sources feed the §15 freshness gate.

## 14. Degradation paths

| Trigger | Path |
|---|---|
| `ortho_2024` display/report denied | Report and portal render without imagery: parcel geometry, findings, tabular evidence, and licensed base layers only. Banner discloses "aerial imagery not licensed for display." This path is the **launch default** until L2 closes and must be demonstrated end-to-end before freeze. |
| Any federal layer `source_unavailable` | Finding rendered as "not assessed — source unavailable at retrieval time"; job continues; freshness gate marks coverage gap. |
| `cama`/`permits` denied or unavailable | Characteristic/permit findings omitted with disclosure; no inference from other sources. |
| `official_records` pending | Finding rendered "pending records request" with disclosed expected timeline (REQ-PERF-03). |
| Municipal FLU endpoint missing | Parcel FLU finding attributed to county only if parcel is unincorporated; otherwise "municipal FLU unavailable — authority: <name>" with disclosure. Never attribute municipal parcels to county FLU. |

## 15. Quality gates

Evaluated by `quality_gates` task before publication (SRS REQ-QG). Output is one of
`auto_publish` | `qualified_output` | `human_review` | `blocked`.

| Gate | Pass | Qualified | Review/Blocked |
|---|---|---|---|
| Parcel identity | Single confirmed identity (REQ-RES) | n/a | Any unresolved ambiguity → **blocked** (identity is mandatory) |
| Freshness | All mandatory datasets within freshness policy | Non-mandatory dataset stale (disclosed) | Mandatory dataset stale → review |
| Coverage | All profile-required datasets returned data | Some datasets empty — disclosed "no record" | Mandatory dataset failed/denied → review |
| Conflict | No unresolved cross-source contradictions | Minor conflict disclosed | Material identity/geometry conflict → review |
| License | All used datasets have `display`/`report` = ✓ | n/a | Any denied/unknown right on required content → **blocked** (never qualified) |

## 16. Acceptance test suite (FL-TST)

Acceptance suite lives in `tests/acceptance/`, runs against recorded fixtures and —
where `query` rights allow — live services. IDs are stable; tests are added, not
renumbered.

| Test | Verifies | Key SRS refs |
|---|---|---|
| FL-TST-01 | Intake normalisation; portfolio row isolation | REQ-INT |
| FL-TST-02 | Address → parcel resolution, happy path | REQ-RES-01/02 |
| FL-TST-03 | Ambiguous match → `AwaitingCustomerInput` → selection resumes job; no silent tie-break | REQ-RES-03/04 |
| FL-TST-04 | Condo/stacked unit-level match + authority routing | REQ-RES-05, REQ-JUR |
| FL-TST-05 | Connector contract + `connectors.validate` harness against fixture | REQ-CON |
| FL-TST-06 | Flood finding: correct zone, panel vintage, three provenance dates | REQ-ANL-03, §13 |
| FL-TST-07 | Wetland indicator phrased as indicator; empty NWI result rendered "no record found," never "no wetlands" | REQ-ANL-04/05 |
| FL-TST-08 | Hydric soils + subsidence findings with vintage | REQ-ANL |
| FL-TST-09 | Permit history + contamination findings; permit docs via pending path | REQ-ANL, §14 |
| FL-TST-10 | FLU finding attributed to correct §3 authority; municipal parcel never county-attributed; access/frontage and utility-proximity findings present | REQ-JUR, REQ-ANL |
| FL-TST-11 | All four gate dispositions exercised; license gate blocks on `null` rights | REQ-QG, §15 |
| FL-TST-12 | Report evidence set reconstructed from audit trail + versioned stores | REQ-AUD-01 |
| FL-TST-13 | Report renders citations + licensing disclosures; §10 boundary language check | REQ-RPT |
| FL-TST-14 | Portal + **imagery-denied degradation** end-to-end | REQ-PTL, REQ-RPT-04, §14 |
| FL-TST-15 | 2-hour SLA smoke on fixture replay; secrets-scan clean | REQ-PERF-01, REQ-SEC |

## 17. Schema drift handling

- `drift_check` fingerprints live `describe()` metadata against the registered schema.
- On mismatch: affected connector's new output is **quarantined** (not applied to new
  jobs); in-flight findings already published are unchanged but logged for review.
- Reviewer confirms the drift; updated field mappings are amended into §9 + registry,
  bumping registry version. Contract test fixtures are regenerated at the same time —
  a mapping update without a fixture update fails CI.

## 18. Freeze criteria

The FL-001 activation freezes — and may serve customer-facing reports — only when all
of the following hold:

1. Launch gates L1–L9 (§12) closed.
2. FL-TST-01 through FL-TST-15 passing on fixtures; FL-TST-14 imagery-denied path
   demonstrated live.
3. Connector contract tests green for every `registered` dataset.
4. §11 rights matrix has **no `null` cells in `display`/`report`** for datasets used by
   `florida_land_screening_v1` — any remaining `null` means that dataset is excluded
   from the frozen profile with a disclosed gap.
5. `registry/volusia.yaml` frozen at a tagged version; all published reports cite it.

## 19. Connector registry seed

`registry/volusia.yaml` is generated from this document (not hand-edited). Schema:

```yaml
registry_version: <semver>            # bumps on any amendment (§9, §17)
activation: FL-001
jurisdiction: volusia_county_fl
planning_authorities:                 # mirror of §3
  - id: volusia_uninc
    name: Volusia County (unincorporated)
    type: county
  # ... one entry per §3 row
providers:
  - id: volusia_county_gis
    name: Volusia County GIS
    base_url: <service root — verified by connectors.validate>
    access: public_anonymous
datasets:
  - id: basemap_parcels
    provider: volusia_county_gis
    access_type: arcgis_query         # §5.2-E
    endpoint: <service/layer path>
    layer_id: <resolved by describe()>
    native_crs: <from describe()>
    expected_fields:                  # §9 contract
      - {name: PARID, type: string, nullable: false}
      # ...
    join_key: parcel_id
    freshness: {policy: monthly, max_age_days: 45}
    vintage: {observation: null, publication: null}   # filled at ingest, never guessed
    license: {name: null, ref: null, gate: L1}
    permissions:                      # §11 — null = unknown = denied
      discover: true
      query: true
      download: true
      cache: null
      retain_derived: null
      display: null
      report: null
      redistribute: false
    status: implementation-ready      # §1.3
    tasks: [fetch_parcels, drift_check, refresh_source]
```

Generation rules:

- One `datasets:` entry per §6 row; one `providers:` entry per §4 row.
- `permissions` copied verbatim from §11; a gate citation annotates the `license` field.
- `expected_fields` populated from `connectors.validate` output on first successful run
  against the live service; until then, from the source's published schema with
  `nullable: true` (unknown) where unverified.
- The file is the input to contract tests and to `drift_check`; divergence between this
  document and the registry fails CI.
