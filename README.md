# Pet Insurance Rating Engine & Rate Order Deployment Pipeline

A masters-level build of a pet-insurance **rating engine** plus an
**Earnix-style** rate deployment workflow (simulation — no Earnix software is
used or required). Six synthetic pricing versions are promoted
**analytical → staging/UAT → production** through sign-off gates, with every
rate change, approver, and timestamp written to an audit log that supports a
machine-checked **100% traceability** claim.

> **ALL DATA SYNTHETIC.** Every rate, filing ID, ZIP code, quote, approver,
> and timestamp in this repo is invented for demonstration. Rate tables are
> modeled on the *public pattern* of a SERFF rate filing (versioned tables,
> effective dates, filing IDs) — these are **not** real filings.

## Measured results (actual output of this repo's code)

| Metric | Value |
|--------|-------|
| Rating factors | **8** (species, breed, age, territory, deductible, reimbursement %, annual limit, discounts) |
| Pricing versions | **6** (v1–v6), all reaching `production` |
| Rate-table rows | **212** factor-values (35 × v1–v4, 36 × v5–v6) |
| Synthetic quotes rated | **12,000** (2,000 per version) |
| Release gates | **18** (3 per version, ordered analytical → staging/UAT → production) |
| Audit rows | **33** (8 `rate_load` + 7 `rate_change` + 6 `version_created` + 6 `uat_passed` + 6 `prod_signoff`) |
| Traceability | **100%** — 15/15 rate changes covered by audit rows, 0 surplus rows |
| Rollbacks | **0** across all 6 versions (promotion gated on passing UAT, by construction) |
| Deployment summaries | **6** (one markdown report per version) |
| Pytest suite | **15 passed** |

Per-version premium outcomes (annual USD, from `outputs/run_report.json`):

| Version | Filing (synthetic) | Effective | Quotes | Min | Median | Max |
|---------|-------------------|-----------|--------|-----|--------|-----|
| v1 | SERFF-SYN-2024-001 | 2024-01-01 | 2,000 | $137.35 | $513.38 | $1,915.25 |
| v2 | SERFF-SYN-2024-002 | 2024-04-01 | 2,000 | $141.59 | $528.22 | $2,535.17 |
| v3 | SERFF-SYN-2024-003 | 2024-07-01 | 2,000 | $152.61 | $533.42 | $2,007.21 |
| v4 | SERFF-SYN-2024-004 | 2024-10-01 | 2,000 | $147.47 | $541.21 | $2,127.29 |
| v5 | SERFF-SYN-2025-001 | 2025-01-01 | 2,000 | $146.47 | $528.68 | $2,679.36 |
| v6 | SERFF-SYN-2025-002 | 2025-04-01 | 2,000 | $145.73 | $540.74 | $2,392.57 |

Reproduce every number above with:

```bash
pip install -r requirements.txt
python -m src.release_pipeline   # rebuilds DB, summaries, snapshots, run_report.json
python -m pytest tests/ -q       # 15 tests, from-scratch pipeline run in tmp DB
```

Quote generation is seeded (`GENERATOR_SEED_BASE + version`) and the engine is
a pure function, so re-runs reproduce these figures exactly. Gate/audit
timestamps are the only run-time values (UTC, recorded at execution).

## How it works

**Rating engine** (`src/rating_engine.py`) — a multiplicative relativity model:

```
annual_premium = base_rate(species)            # dog $480 / cat $300 per year
               × f(breed) × f(age band) × f(territory)
               × f(deductible) × f(reimbursement) × f(annual_limit)
               × Π f(discount applied)
```

Pure function of `(policy, rate_table)`: no randomness, no I/O — identical
inputs always yield an identical premium (asserted by tests, including a
hand-computed regression case).

**Versioned rate tables** (`src/rate_tables.py`, `rate_tables/*.json`,
`rate_factor_values` table) — v1 is the full 8-factor load; v2–v6 apply
declared deltas (senior age-band trend, territory re-tiering, breed refresh,
new annual-pay discount, high-tier repricing). `diff_tables()` computes the
exact change set between versions.

**Release pipeline** (`src/release_pipeline.py`) — per version:

1. **Analytical** — build & persist the rate table; audit `version_created` +
   one row per change. Gate sign-off: `pricing_analyst`.
2. **Staging / UAT** — rate 2,000 seeded quotes; run the 5-check battery
   (factor-table completeness, quote factor coverage across all 8 factors,
   engine determinism on 25 policies × 3 ratings, premium sanity bounds
   $50–$5,000, audit-trail presence). **All checks must pass** — the pipeline
   asserts this before promotion. Gate sign-off: `uat_lead`.
3. **Production** — record `prod_signoff` (`release_manager`), set status to
   `production`, emit the deployment summary.

Zero rollbacks is a construction guarantee, not luck: a version cannot reach
production without passing UAT, and the suite asserts no `rollback` audit rows
and no `rolled_back` versions exist.

**Audit & verifiability** (`src/audit.py`) — `verify_complete_traceability()`
diffs consecutive tables and requires a matching audit row for every change
(and rejects surplus rows). The suite re-runs the entire pipeline from scratch
and asserts 100%.

## Repository layout

```
├── sql/schema.sql                  # DDL (PostgreSQL-compatible; runs on SQLite as-is)
├── src/
│   ├── rating_engine.py            # 8-factor premium calculator (pure function)
│   ├── rate_tables.py              # 6 versioned tables + deltas + diff
│   ├── data_generator.py           # seeded synthetic quote generator (all 8 factors)
│   ├── release_pipeline.py         # analytical → staging/UAT → production, gates, summaries
│   ├── audit.py                    # audit logging + 100% traceability check
│   └── db.py                       # SQLite connection helpers
├── rate_tables/                    # JSON snapshot per version (build artifact)
├── outputs/
│   ├── deployment_summaries/       # 6 per-version deployment reports (build artifact)
│   └── run_report.json             # machine-readable run metrics (build artifact)
├── docs/
│   ├── data_dictionary.md          # factors, tables, version history
│   └── architecture.md             # components, stages, reproducibility
└── tests/test_rating.py            # 15 tests: 8 factors, 6 versions, gate order,
                                    # audit completeness, zero rollbacks, determinism…
```

## Honest labeling notes

- **PostgreSQL**: no Postgres server was available in the build environment, so
  the pipeline runs on **SQLite**. The DDL in `sql/schema.sql` uses standard
  SQL only and runs unmodified on PostgreSQL — same table/column names; point
  it at a Postgres server to use it there. The database file itself
  (`data/pet_rating.db`) is a rebuildable artifact and is git-ignored.
- **Earnix**: this is an Earnix-*style* staged deployment workflow written from
  scratch; no Earnix product is involved.
- **SERFF**: filing IDs (`SERFF-SYN-…`) follow the public *pattern* of SERFF
  filings; they are synthetic identifiers, not real filings.
- **Approvers** are role IDs (`pricing_analyst`, `uat_lead`, `release_manager`),
  not real people.
