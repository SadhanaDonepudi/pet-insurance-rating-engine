# Data Dictionary

**ALL DATA SYNTHETIC.** Every table, rate, filing ID, ZIP code, and approver in
this project is invented for demonstration. Nothing here is a real rate filing.

## Rating factors (exactly 8)

| # | Factor | Description | Rated values |
|---|--------|-------------|--------------|
| 1 | `species` | Pet species; priced through the base rate (dog $480/yr, cat $300/yr). Table relativity held at 1.0 by construction | dog, cat |
| 2 | `breed` | Breed risk relativity within species | 10 breeds (5 dog, 5 cat) |
| 3 | `age` | Age band derived from `age_years` | under_1, 1_to_5, 6_to_9, 10_plus |
| 4 | `territory` | Rating territory derived from ZIP code | urban_core, urban, suburban, small_town, rural |
| 5 | `deductible` | Annual deductible (USD) | 100, 250, 500, 750, 1000 |
| 6 | `reimbursement` | Reimbursement percentage | 70, 80, 90 |
| 7 | `annual_limit` | Annual benefit limit (USD; `unlimited` = no cap) | 5000, 10000, 15000, unlimited |
| 8 | `discounts` | Stackable discounts, combined multiplicatively | multi_pet (v1+), wellness_plan (v1+), annual_pay (v5+) |

Premium formula (multiplicative relativity model):

```
annual_premium = base_rate(species)
               × f(breed) × f(age band) × f(territory)
               × f(deductible) × f(reimbursement) × f(annual_limit)
               × Π f(discount applied)
```

## Tables

### `rating_factors`
Static list of the 8 rating factors. Columns: `factor_id`, `factor_name`, `description`.

### `rate_versions`
One row per pricing version (exactly 6: v1–v6).

| Column | Type | Meaning |
|--------|------|---------|
| `version_id` | INTEGER PK | 1–6 |
| `version_label` | TEXT | `v1` … `v6` |
| `filing_id` | TEXT | Synthetic filing ID in SERFF *pattern* (`SERFF-SYN-YYYY-NNN`); not a real filing |
| `effective_date` | TEXT | ISO date the version's rates take effect |
| `status` | TEXT | `analytical` → `staging_uat` → `production` (no `rolled_back` rows exist) |
| `created_at` | TEXT | Build timestamp (UTC, run-time) |
| `notes` | TEXT | Business rationale for the version |

### `rate_factor_values`
The versioned rate tables: 212 rows total (35 factor-values × v1–v4, 36 × v5–v6;
v5 adds the `annual_pay` discount value).

| Column | Type | Meaning |
|--------|------|---------|
| `id` | INTEGER PK | — |
| `version_id` | INTEGER FK | Pricing version |
| `factor_name` | TEXT | One of the 8 factors |
| `factor_value` | TEXT | Rated value, e.g. `french_bulldog`, `500`, `90` |
| `relativity` | REAL | Multiplicative relativity vs the factor base |

### `quotes`
12,000 synthetic quotes (2,000 per version), each rated by the engine against
its version's table. Columns mirror the 8 rating inputs plus
`annual_premium`, `territory` (derived), `version_id`, and `created_at`.
`discounts` is stored as a JSON array of applied discount codes.

### `release_gates`
Sign-off gates: 18 rows (3 per version). `stage` ∈ {analytical, staging_uat,
production}, ordered by global monotonic `seq`. Each row records the
role-based approver (`pricing_analyst`, `uat_lead`, `release_manager`) and a
UTC timestamp.

### `audit_log`
33 rows. Every rate-table change and every gate event:

| `change_type` | Rows | Meaning |
|---------------|------|---------|
| `rate_load` | 8 | v1 initial load, one row per factor |
| `rate_change` | 7 | v2–v6 deltas (1+1+1+2+2), old → new relativity with rationale |
| `version_created` | 6 | Analytical build per version |
| `uat_passed` | 6 | Staging/UAT sign-off per version |
| `prod_signoff` | 6 | Production deployment approval per version |
| `rollback` | 0 | None — promotion is gated on passing UAT |

## Version history (synthetic filings)

| Version | Filing ID (synthetic) | Effective | Change |
|---------|----------------------|-----------|--------|
| v1 | SERFF-SYN-2024-001 | 2024-01-01 | Initial 8-factor table load (35 values) |
| v2 | SERFF-SYN-2024-002 | 2024-04-01 | age.10_plus 1.60 → 1.75 (senior trend) |
| v3 | SERFF-SYN-2024-003 | 2024-07-01 | territory.urban_core 1.20 → 1.28 (re-tiering) |
| v4 | SERFF-SYN-2024-004 | 2024-10-01 | breed.french_bulldog 1.35 → 1.42 |
| v5 | SERFF-SYN-2025-001 | 2025-01-01 | +discounts.annual_pay 0.98; deductible.100 1.35 → 1.38 |
| v6 | SERFF-SYN-2025-002 | 2025-04-01 | reimbursement.90 1.15 → 1.18; annual_limit.unlimited 1.20 → 1.24 |

Total audited rate changes: 15 (8 loads + 7 deltas) — traceability 100%.
