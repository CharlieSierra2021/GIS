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

| # | Tasking | Phase | Contract | Done looks like | Doc updates |
|---|---------|-------|----------|-----------------|-------------|
| 1 | Rights procurement tracker | P0 | ICD §11/§12 | Gate matrix L1–L9 with owner + evidence link per gate | §11 cells flip with gate citations |
| 2 | Compose bring-up + Dockerfile | P1 | README §Getting started, SOW D8 | `docker compose up` + `alembic upgrade head` runs clean | README if commands change |
| 3 | Parcel resolution service | P1 | SRS REQ-RES, ICD §9 | Labelled validation set passes; ambiguity → `AwaitingCustomerInput`; no silent tie-breaks | — |
| 4 | Jurisdiction router | P1 | SRS REQ-JUR, ICD §3 | All 18 authorities (county + 17 municipal) routable from `mun_boundaries`; wrong attribution impossible | — |
| 5 | Connector contract + `connectors.validate` harness | P2 | ICD §5, README §harness | `python -m connectors.validate --provider volusia_county_gis --dataset basemap_parcels` emits registry-ready fixture | expected_fields populated in registry |
| 6 | Per-provider adapters | P2 | ICD §4/§6 | Contract test + fixture per dataset; failure classes per §5.3 | §6 status → `registered` as rights confirm |
| 7 | Storage + provenance layer | P2 | SRS REQ-DAT | Three provenance dates per record; audit trail per job | — |
| 8 | `florida_land_screening_v1` engine | P3 | SRS REQ-ANL | Nine screening areas produce cited findings; absence-of-evidence phrasing enforced | ICD §10 if new claim types |
| 9 | Quality gates + dispositions | P4 | ICD §15, SRS REQ-QG | Four dispositions exercised; license gate blocks on `null` | — |
| 10 | Report publisher + portal | P4 | SRS REQ-RPT/PTL | PDF + manifest; portal renders with rights-filtered layers | — |
| 11 | **Imagery-denied path E2E** | P4 | ICD §14, FL-TST-14 | Full report/portal renders with zero imagery — launch blocker | §11/L2 outcome |
| 12 | FL-TST acceptance suite | P5 | ICD §16 | FL-TST-01…15 green on fixtures | — |
| 13 | Freeze review | P5 | ICD §18 | Five freeze criteria met; registry tagged | README launch status |

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
