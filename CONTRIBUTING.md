# Contributing — docs-as-code pipeline

This repository is documentation-first: the docs are the contract, the code implements
them. Read `README.md`, then `docs/SOW.md`, `docs/SRS.md`, `docs/ICD-FL-001.md` — in
that order — before writing code.

## Golden rules (non-negotiable)

1. **Docs are normative.** If the ICD says a permission is `null`, the code treats it as
   denied. If behaviour and docs disagree, either the code is wrong or the doc needs an
   amendment — never silently diverge.
2. **Amend docs before/with code, never after.** Dataset inventory, rights, profiles,
   and the product boundary change via ICD/SRS/SOW amendment (SOW §9) in the same PR as
   the code that implements them.
3. **`registry/volusia.yaml` is generated, not hand-edited** (ICD §19). Change the ICD,
   regenerate the registry, bump `registry_version`.
4. **`null` = unknown = denied.** Never populate a rights cell or a source date from an
   assumption.
5. **Boundary language is reviewed.** No finding may imply survey, flood determination,
   delineation, or zoning/buildability conclusions (SRS §1.3, ICD §10).
6. **FL-TST IDs are stable.** Add tests, never renumber (ICD §16).
7. **No secrets.** `deploy/env.example` documents variable names only (SRS REQ-SEC-01).

## Pipeline per pull request

Every PR must keep the docs coherent. Checklist:

- [ ] Requirement implemented maps to a REQ-* ID in `docs/SRS.md` (add one if new).
- [ ] Acceptance path exists: contract test (`tests/connectors/`), validation case
      (`tests/resolution/`), or FL-TST (`tests/acceptance/`).
- [ ] If a registry/dataset/right changed: ICD amended + `volusia.yaml` regenerated +
      `registry_version` bumped.
- [ ] README updated when layout, commands, status, or phase changes.
- [ ] New findings language checked against ICD §10 permitted-claims column.
- [ ] CI: markdown lint, `yamllint registry/`, secrets scan, connector contract tests.

## Work ahead — task board

Ordered to SOW §5 phases. Pick from the top; each row lists its doc contract and the
update owed when it lands.

Status legend: `done (commit)` = merged on main with tests; `partial` = core landed, listed
gap remains; blank = not started.

| # | Tasking | Phase | Contract | Done looks like | Doc updates | Status |
|---|---------|-------|----------|-----------------|-------------|--------|
| 1 | Rights procurement tracker | P0 | ICD §11/§12 | Gate matrix L1–L9 with owner + evidence link per gate | §11 cells flip with gate citations | |
| 2 | Compose bring-up + Dockerfile | P1 | README §Getting started, SOW D8 | `docker compose up` + `alembic upgrade head` runs clean | README if commands change | partial — M14 adds installed-wheel startup regression, explicit registry path, packaged portal templates and migrations in the Docker context; Docker/Compose remain unverified |
| 3 | Parcel resolution service | P1 | SRS REQ-RES, ICD §9 | Labelled validation set passes; ambiguity → `AwaitingCustomerInput`; no silent tie-breaks | — | done (a38ea54) — 13-case validation set, FL-TST-02/03/04 |
| 4 | Jurisdiction router | P1 | SRS REQ-JUR, ICD §3 | All 18 authorities (county + 17 municipal) routable from `mun_boundaries`; wrong attribution impossible | — | done (c7bb466) — FL-TST-10 partial |
| 5 | Connector contract + `connectors.validate` harness | P2 | ICD §5, README §harness | `python -m connectors.validate --provider volusia_county_gis --dataset basemap_parcels` emits registry-ready fixture | expected_fields populated in registry | done (a4bbacf) — harness exits 2 until an endpoint is registered |
| 6 | Per-provider adapters | P2 | ICD §4/§6 | Contract test + fixture per dataset; failure classes per §5.3 | §6 status → `registered` as rights confirm | partial — ArcGIS (a4bbacf, 952ae27), `file_download` + GeoJSON ingest (75baf8c), `records_request` + rescreen (210eff6); `document_retrieval` and Shapefile/GDB ingest pending |
| 7 | Storage + provenance layer | P2 | SRS REQ-DAT | Three provenance dates per record; audit trail per job | — | done (6646232) — SQL stores, append-only audit, evidence reconstruction, FL-TST-12; PostGIS geometry columns still pending |
| 8 | `florida_land_screening_v1` engine | P3 | SRS REQ-ANL | Nine screening areas produce cited findings; absence-of-evidence phrasing enforced | ICD §10 if new claim types | done on fixtures (15fc7d3) — FL-TST-06/07; EPSG:3087 measurement via pyproj landed in M12 (75baf8c) |
| 9 | Quality gates + dispositions | P4 | ICD §15, SRS REQ-QG | Four dispositions exercised; license gate blocks on `null` | — | done (1dc562b) — FL-TST-11 |
| 10 | Report publisher + portal | P4 | SRS REQ-RPT/PTL | PDF + manifest; portal renders with rights-filtered layers | — | done (3e1cce8, f898707) — HTML + manifest, portal with `layers.geojson`; PDF renderer deploy-time |
| 11 | **Imagery-denied path E2E** | P4 | ICD §14, FL-TST-14 | Full report/portal renders with zero imagery — launch blocker | §11/L2 outcome | done on fixtures (3e1cce8, f898707) — report + portal; live demo before freeze still owed |
| 12 | FL-TST acceptance suite | P5 | ICD §16 | FL-TST-01…15 green on fixtures | — | partial — 01-07, 09-14 on fixtures; 08 (soils/subsidence detail) and 15 (SLA smoke + secrets scan) open |
| 13 | Freeze review | P5 | ICD §18 | Five freeze criteria met; registry tagged | README launch status | |
| 14 | API jobs + Celery wiring | P3 | ICD §8, SRS REQ-INT | `POST /jobs` → resolve → route → fetch → screen → gates; `AwaitingCustomerInput` round-trip via API; task names per ICD §8 | README commands | done (a79c6a8) |
| 15 | Registry-backed `EvidenceFetcher` | P2 | ICD §5/§6 | `analysis.engine.EvidenceFetcher` implemented over `ArcGISFeatureServiceConnector` + registry rights | — | done (952ae27) |
| 16 | Real auth (replace `X-Account-Id`) | P4 | SRS REQ-SEC-03 | Per-account tokens; store isolation unchanged | README API table | |
| 17 | PostGIS geometry columns + spatial store | P2 | SRS REQ-DAT-01/03 | Source + derived geometries as PostGIS types; alembic revision | — | |
| 18 | Ortho tile layer (licensed branch) + PDF renderer | P4 | ICD §11 L2, REQ-RPT-01 | WeasyPrint in deploy image; tiles only when `ortho_2024` display+report ✓ | — | |

### M14–M15 deployment and rights follow-up

- M14 (`40ae538`): non-editable wheel resources and explicit `PI_REGISTRY_PATH`;
  wheel startup tested outside the checkout. Docker/Compose remain unverified.
- M15: published evidence GeoJSON requires both current display permission and the
  historical manifest allowlist. Removed datasets and missing publication metadata
  fail closed; regression tests cover revocation and restoration without changing the
  historical manifest.
- Next release-blocking work: real authentication (row 16), then rights checks across
  raw job/audit/evidence JSON, stored report downloads, source-derived parcel/candidate
  geometry, and file-download cache retention. M15 does not certify these other paths.
- Fixture tests passing is not equivalent to closing launch gates or proving remote CI
  passed. Record local, hosted CI, container and live-source results separately.

### Pick-up protocol

Every milestone commit on `main` ends with a **Pick-up point** paragraph naming the next
tasking and the seams to build on. To resume: `git log --grep="Pick-up point" -1`, read
that paragraph, then take the matching board row. Run `pytest -q` first — the count in the
latest commit message is the baseline you must not regress.

## Commit conventions

Small, meaningful commits — one logical change each:

- `docs:` doc amendments (SRS/ICD/SOW/registry narrative)
- `feat:` new capability tied to a REQ-* or FL-TST ID
- `fix:` bug fixes
- `chore:` scaffolding, deps, config
- `test:` test-only changes

Reference the governing ID in the body, e.g. `implements REQ-RES-05`,
`verifies FL-TST-03`, `amends ICD §11 per L2`.

## Status protocol

When a phase exits (SOW §5 criteria met): update README §Launch status + the phase
table in the relevant doc, tag the commit, and announce in the PR description which
FL-TST tests it unblocks.
