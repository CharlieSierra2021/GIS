# Statement of Work — GIS Property Intelligence Platform

**Project:** GIS Property Intelligence Platform ("the Platform")
**Launch geography:** Volusia County, Florida
**Document status:** Implementation-ready, rights-pending
**Companion documents:** `docs/SRS.md` (normative requirements), `docs/ICD-FL-001.md`
(Volusia County data-source interface control document)

---

## 1. Purpose

This Statement of Work defines the scope, deliverables, phases, acceptance criteria, and
exclusions for build-out of the Platform: an automated, drone-free property due-diligence
and land-intelligence service that resolves a property, discovers and fuses the
authoritative public and licensed datasets for its jurisdiction, applies configurable
analysis profiles, and publishes a traceable screening report.

The Platform launches in Volusia County, Florida, on a statewide connector framework that
is activated county by county. All work under this SOW targets the Volusia activation
unless explicitly stated otherwise.

## 2. Product boundary

The product boundary defined in `docs/SRS.md` §1.3 and `docs/ICD-FL-001.md` §10 is
incorporated into this SOW by reference. In summary, the Platform delivers a
due-diligence **screening** product and **does not** deliver land surveys, certified
boundaries, lending-compliant flood determinations, wetland delineations, environmental
assessments, or zoning/buildability determinations.

This boundary is contractual as well as technical: deliverables, report language, and
acceptance tests SHALL be written so that no output overstates the evidentiary weight
of the underlying data.

## 3. Scope of work

### 3.1 In scope

| # | Work item | Summary |
|---|-----------|---------|
| S1 | Customer intake | Address, parcel ID, geometry, and portfolio CSV intake via API and portal |
| S2 | Parcel resolution | Parcel identity resolution including ambiguity handling (`AwaitingCustomerInput`) and condo/stacked-parcel unit-level matching |
| S3 | Jurisdiction routing | Municipal vs. county planning-authority resolution per ICD-FL-001 §3 |
| S4 | Connector framework | One adapter per provider on a common contract; ArcGIS REST, file download, document retrieval, and records-request connector types |
| S5 | Volusia connector set | Adapters and registry entries for all datasets catalogued in ICD-FL-001 §6 |
| S6 | Source registry | Per-dataset record of authority, vintage, license, freshness, and permissions; deny-by-default rights model |
| S7 | Storage & provenance | PostGIS spatial store, versioned object store, and audit trail capturing observation/publication/retrieval dates separately |
| S8 | Florida screening engine | `florida_land_screening_v1` profile: flood, wetlands, hydric soils, subsidence, permits, contamination, land use, access, utilities |
| S9 | Quality gates | Freshness, coverage, conflict, and license gates feeding the auto-publish / qualified-output / human-review / blocked decision |
| S10 | Report publisher | HTML-template reports rendered to PDF, with source citations and licensing disclosure on every finding |
| S11 | Customer portal | Leaflet/OpenLayers map viewer for results, candidate selection for ambiguous resolutions, and report download |
| S12 | Deployment | Docker Compose single-host deployment with documented configuration and no secrets in the repo |

### 3.2 Out of scope

| # | Excluded item | Notes |
|---|---------------|-------|
| X1 | Activations beyond Volusia County | Framework is statewide; data-source ICDs for other counties are separate efforts |
| X2 | Drone/UAS data acquisition | The platform is drone-free by design |
| X3 | Professional survey or boundary certification | See §7 exclusions |
| X4 | Lending-compliant flood determinations (Life-of-Loan) | Requires a flood-determination vendor; not in scope |
| X5 | Field verification / wetland delineation | Screening uses published data only |
| X6 | Municipal permitting workflows | Permits are read as risk signals, not acted upon |
| X7 | White-label resale of licensed data | Redistribution rights are denied unless explicitly licensed |

## 4. Deliverables

| ID | Deliverable | Definition of done |
|----|-------------|--------------------|
| D1 | Documentation set | SOW, SRS, ICD-FL-001 current, mutually consistent, and version-controlled |
| D2 | Connector framework + registry | Common connector contract implemented; `registry/volusia.yaml` seeds all ICD §6 datasets; validation harness runs against a live service |
| D3 | Parcel resolution service | Address/parcel/geometry resolution with ambiguity workflow; condo/stacked-parcel unit matching; labelled validation set passing in `tests/resolution/` |
| D4 | Jurisdiction router | Planning-authority resolution for all Volusia municipalities; wrong-authority statements impossible by construction |
| D5 | Screening engine | `florida_land_screening_v1` produces per-finding provenance, vintage, and license disclosure |
| D6 | Quality gate system | Gates per ICD §15; publication decisions logged with gate outcomes |
| D7 | Report publisher + portal | Reports render to PDF; portal displays results and handles candidate selection; imagery-denied degradation path demonstrated end-to-end |
| D8 | Deployment package | `deploy/docker-compose.yml` + `env.example`; clean-environment bring-up documented |
| D9 | Acceptance evidence | FL-TST suite results and launch-gate checklist per ICD §16 and §12 |

## 5. Phases and milestones

| Phase | Name | Exit criteria |
|-------|------|---------------|
| P0 | Rights & procurement | Launch gates L1–L6 (ICD §12) closed or formally waived with residual-risk note; registry rights columns populated |
| P1 | Resolution & routing | D3, D4 complete; FL-TST-01 through FL-TST-04 passing |
| P2 | Connectors & registry | D2 complete; each registered dataset passing its schema-drift contract test; FL-TST-05 |
| P3 | Screening engine | D5 complete; FL-TST-06 through FL-TST-10 passing on fixtures |
| P4 | Gates & publishing | D6, D7 complete; FL-TST-11 through FL-TST-14 passing; imagery-denied path demonstrated |
| P5 | Acceptance & freeze | D8, D9 complete; launch gates L7–L9 closed; ICD freeze criteria (§18) satisfied |

Phase P0 is intentionally sequenced first: most launch gates are procurement and legal
verifications, not engineering. Engineering that assumes a right that is not yet procured
must build the deny-path first.

## 6. Acceptance

Acceptance requires all of the following:

1. **Acceptance tests.** The FL-TST acceptance suite (`tests/acceptance/`, defined in
   ICD-FL-001 §16) passes against recorded fixtures and, where permitted, live services.
2. **Launch gates.** Gates L1–L9 (ICD-FL-001 §12) are closed. Gates are binary;
   "partially licensed" is not a pass.
3. **Boundary compliance.** A document review confirms no report template, API field, or
   UI string states or implies an excluded service (§3.2, §7).
4. **Degradation demonstration.** The imagery-denied degradation path (ICD §14) is shown
   end-to-end before freeze — the highest-risk launch item per the README.

## 7. Exclusions and disclaimers

The following are permanently excluded from deliverables and from any claim the Platform
makes in customer-facing output:

- Land surveys, certified or uncertified boundary determinations
- Flood determinations compliant with lender/regulatory requirements
- Wetland delineations, jurisdictional determinations, or environmental assessments
- Zoning verifications or buildability/development-rights determinations
- Title opinions, lien searches, or other instruments of conveyance
- Any representation that absence of a record (e.g., no wetland polygon intersecting the
  parcel) constitutes evidence of absence of the condition

## 8. Assumptions and dependencies

- Public availability of a dataset does **not** imply commercial report/display rights;
  procurement tasks in P0 exist because rights must be confirmed per dataset.
- County orthoimagery display/report rights are treated as denied until confirmed; the
  2024 ortho service was processed by a commercial vendor (see ICD §11).
- Source APIs remain materially stable; schema drift is detected by contract tests and
  handled per ICD §17 rather than assumed away.
- Records-request workflows (where needed) operate on county timelines outside SLA
  control; affected findings are reported as pending or unavailable, never fabricated.

## 9. Change control

Changes to dataset inventory, rights status, analysis profiles, or the product boundary
are made by amendment to ICD-FL-001 (data sources/rights) or SRS (system behaviour).
Changes to scope, schedule, or deliverables are amendments to this SOW.
