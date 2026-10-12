# Architecture

## Overview

An Earnix-**style** rate deployment workflow (simulation only — no Earnix
software is used) for a pet-insurance rating engine. Six synthetic pricing
versions move through a gated release pipeline — analytical → staging/UAT →
production — with every rate change, approver, and timestamp written to an
audit log that supports a machine-checkable 100% traceability claim.

```
                    ┌─────────────────────┐
                    │  src/rate_tables.py │  6 versioned tables (v1 + deltas)
                    └─────────┬───────────┘
                              │
┌─────────────────┐   ┌───────▼────────┐   ┌──────────────────────┐
│ src/rating_     │   │ src/release_   │   │ src/data_generator.py│
│ engine.py       │◄──│ pipeline.py    │──►│ 2,000 seeded quotes  │
│ 8-factor model  │   │ analytical →   │   │ per version          │
└─────────────────┘   │ staging/UAT →  │   └──────────────────────┘
                      │ production     │
                      └───────┬────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
     release_gates    audit_log (33)    quotes (12,000)
     (18 sign-offs)   100% traceable    rated premiums
```

## Components

| File | Responsibility |
|------|----------------|
| `src/rating_engine.py` | Pure-function premium calculator over exactly 8 factors; no I/O, no randomness |
| `src/rate_tables.py` | v1 table + per-version deltas; `build_version_table(v)`, `diff_tables()` |
| `src/data_generator.py` | Seeded synthetic quote generator exercising all 8 factors, with a coverage-repair guarantee |
| `src/release_pipeline.py` | Gated promotion pipeline, UAT battery, deployment summaries, JSON snapshots |
| `src/audit.py` | Audit logging + `verify_complete_traceability()` (the 100% check) |
| `src/db.py` | SQLite connection + schema init (PostgreSQL-compatible DDL) |
| `sql/schema.sql` | DDL for all 6 tables |
| `tests/test_rating.py` | 15 pytest tests asserting every headline number |

## Release pipeline stages

1. **Analytical** — build the version's rate table (v1 full load; v2–v6 = previous
   table + deltas), persist 35/36 factor-values, write `version_created` plus
   one audit row per change. Gate recorded with approver `pricing_analyst`.
2. **Staging / UAT** — generate 2,000 seeded quotes, rate them, and run the
   5-check battery (factor-table completeness, quote factor coverage,
   engine determinism, premium sanity bounds, audit-trail presence). **All
   checks must pass**; the pipeline asserts this, so a version can never be
   promoted on a failed check. Gate recorded with approver `uat_lead`.
3. **Production** — record `prod_signoff` (approver `release_manager`), flip
   version status to `production`, and emit a per-version deployment summary
   markdown under `outputs/deployment_summaries/`.

Because promotion is impossible without passing UAT, rollbacks are **zero by
construction** — asserted by the pipeline, the audit log (no `rollback` rows),
and the test suite.

## Data & reproducibility

- **Synthetic everything**: rates, filings, ZIPs, quotes, approvers, timestamps
  of record (timestamps are run-time UTC; everything else is seeded).
- **Seeded generation**: `GENERATOR_SEED_BASE + version` makes the 12,000
  quotes byte-identical across runs; the engine is a pure function.
- **SQLite locally, PostgreSQL-ready**: no Postgres server was available in the
  build environment, so the pipeline runs on SQLite. The DDL uses standard SQL
  only — the same `sql/schema.sql` runs unmodified on PostgreSQL (see README).

## Verifiability

`Auditor.verify_complete_traceability()` diffs consecutive version tables and
requires a matching audit row for every difference (and no unmatched audit
rows). The pytest suite re-runs the whole pipeline from scratch in a tmp
database and asserts: 8 factors, 6 versions, gate order, 100% traceability
(15/15 changes), 33 audit rows, 0 rollbacks, engine determinism, quote
coverage, premium bounds, and 6 deployment summaries.
