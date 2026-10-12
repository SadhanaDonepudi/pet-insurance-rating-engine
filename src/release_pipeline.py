"""Release pipeline: analytical -> staging/UAT -> production.

Earnix-STYLE workflow simulation (no Earnix software is used or required):
each of the 6 pricing versions is built in `analytical`, validated in
`staging_uat`, and only promoted to `production` after every UAT check passes
and a sign-off (approver + timestamp) is recorded at each gate.

Because promotion is gated on passing UAT, rollbacks are zero by
construction; the pipeline asserts this and every deployment summary reports
it explicitly.

ALL DATA SYNTHETIC.
"""

import json
import os
import statistics
from pathlib import Path
from typing import Dict, List

from .audit import Auditor
from .data_generator import coverage_report, generate_quotes, utcnow_iso
from .db import connect, init_schema
from .rate_tables import VERSIONS, RateTable, build_version_table, diff_tables
from .rating_engine import RATING_FACTORS, factor_value_count, rate_premium

# ---- pipeline configuration (deterministic) ------------------------------
QUOTES_PER_VERSION = 2000
GENERATOR_SEED_BASE = 20240101
PREMIUM_MIN, PREMIUM_MAX = 50.0, 5000.0   # UAT sanity bounds (USD / year)
DETERMINISM_SAMPLE = 25                   # fixed policies re-rated 3x each

# Role-based synthetic approvers (no real people).
APPROVER_ANALYTICAL = "pricing_analyst"
APPROVER_UAT = "uat_lead"
APPROVER_PROD = "release_manager"

STAGES = ["analytical", "staging_uat", "production"]
ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# UAT checks (staging gate)
# ---------------------------------------------------------------------------
def _fixed_sample_policies(rate_table: RateTable) -> List[Dict]:
    """Deterministic sample of policies spanning all 8 factors."""
    import random
    rng = random.Random(999)
    breeds = [b for vs in rate_table["breed"] for b in [vs]]
    from .rating_engine import BREED_TO_SPECIES, TERRITORY_ZIPS
    zips = [z for zs in TERRITORY_ZIPS.values() for z in zs]
    discs = sorted(rate_table["discounts"])
    policies = []
    for i in range(DETERMINISM_SAMPLE):
        species = "dog" if i % 2 == 0 else "cat"
        breed = rng.choice([b for b in breeds
                            if BREED_TO_SPECIES[b] == species])
        policies.append({
            "species": species, "breed": breed,
            "age_years": [0.5, 3.0, 7.0, 12.0][i % 4],
            "zip_code": zips[i % len(zips)],
            "deductible": [100, 250, 500, 750, 1000][i % 5],
            "reimbursement": [70, 80, 90][i % 3],
            "annual_limit": ["5000", "10000", "15000", "unlimited"][i % 4],
            "discounts": [discs[i % len(discs)]] if i % 3 == 0 else [],
        })
    return policies


def run_uat_checks(conn, version_id: int, version: int,
                   rate_table: RateTable, quotes: List[Dict]) -> List[Dict]:
    """Run the staging/UAT check battery. Returns per-check results."""
    results = []

    # 1. rate table covers exactly the 8 rating factors
    counts = factor_value_count(rate_table)
    results.append({
        "check": "factor_table_completeness",
        "passed": set(counts) == set(RATING_FACTORS) and all(v > 0 for v in counts.values()),
        "detail": f"{len(counts)} factors, {sum(counts.values())} factor-values",
    })

    # 2. generated quotes exercise all 8 factors (>= 2 distinct values each)
    cov = coverage_report(quotes)
    results.append({
        "check": "quote_factor_coverage",
        "passed": all(v >= 2 for v in cov.values()),
        "detail": json.dumps(cov),
    })

    # 3. engine determinism: re-rate fixed sample 3x, all identical
    sample = _fixed_sample_policies(rate_table)
    det_ok = all(
        len({rate_premium(p, rate_table) for _ in range(3)}) == 1
        for p in sample)
    results.append({
        "check": "engine_determinism",
        "passed": det_ok,
        "detail": f"{len(sample)} policies x 3 ratings identical",
    })

    # 4. premium sanity bounds
    premiums = [q["annual_premium"] for q in quotes]
    results.append({
        "check": "premium_bounds",
        "passed": all(PREMIUM_MIN <= p <= PREMIUM_MAX for p in premiums),
        "detail": f"min={min(premiums):.2f} max={max(premiums):.2f} "
                  f"bounds=[{PREMIUM_MIN:.0f},{PREMIUM_MAX:.0f}]",
    })

    # 5. audit trail present for this version (creation + changes)
    n_audit = conn.execute(
        "SELECT COUNT(*) c FROM audit_log WHERE version_id = ?",
        (version_id,)).fetchone()["c"]
    results.append({
        "check": "audit_trail_present",
        "passed": n_audit > 0,
        "detail": f"{n_audit} audit rows for version v{version}",
    })
    return results


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class ReleasePipeline:
    def __init__(self, db_path: str, summaries_dir: str):
        self.db_path = db_path
        self.summaries_dir = Path(summaries_dir)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)
        self.conn = connect(db_path)
        init_schema(self.conn)
        self.auditor = Auditor(self.conn)
        self._gate_seq = self._max_gate_seq()
        self.report: Dict = {"versions": [], "rollbacks": 0}

    def _max_gate_seq(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) s FROM release_gates").fetchone()
        return row["s"]

    def _record_gate(self, version_id, stage, gate_name, approver,
                     checks_passed: int):
        self._gate_seq += 1
        self.conn.execute(
            """INSERT INTO release_gates
               (version_id, stage, gate_name, approver, approved_at, seq,
                checks_passed)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (version_id, stage, gate_name, approver, utcnow_iso(),
             self._gate_seq, checks_passed))
        self.conn.commit()

    def _set_status(self, version_id: int, status: str):
        self.conn.execute("UPDATE rate_versions SET status = ? WHERE version_id = ?",
                          (status, version_id))
        self.conn.commit()

    def run(self) -> Dict:
        print("=== Pet Insurance Rating Engine — release pipeline ===")
        print("ALL DATA SYNTHETIC | Earnix-style workflow simulation")
        for meta in VERSIONS:
            self._run_version(meta)
        self._export_rate_table_snapshots()
        # global verifiability: 100% traceability of every rate change
        trace = self.auditor.verify_complete_traceability()
        self.report["traceability"] = trace
        print(f"\nTraceability: {trace['traceability_pct']:.1f}% "
              f"({trace['audited_changes']}/{trace['expected_changes']} changes audited)")
        print(f"Rollbacks: {self.report['rollbacks']}")
        return self.report

    def _export_rate_table_snapshots(self) -> None:
        """Write one JSON snapshot per version into rate_tables/ (review artifact)."""
        out_dir = ROOT / "rate_tables"
        out_dir.mkdir(parents=True, exist_ok=True)
        for meta in VERSIONS:
            v = meta["version"]
            snapshot = {
                "synthetic": True,
                "filing_id": meta["filing_id"],
                "version": meta["label"],
                "effective_date": meta["effective_date"],
                "notes": meta["notes"],
                "rating_factors": RATING_FACTORS,
                "rate_table": build_version_table(v),
            }
            path = out_dir / f"{meta['label']}_{meta['filing_id']}.json"
            path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"  rate table snapshots -> {out_dir} ({len(VERSIONS)} files)")

    def _run_version(self, meta: Dict):
        v, label = meta["version"], meta["label"]
        print(f"\n--- {label} ({meta['filing_id']}) effective {meta['effective_date']} ---")
        table = build_version_table(v)

        # ---- Stage 1: analytical -------------------------------------
        cur = self.conn.execute(
            """INSERT INTO rate_versions
               (version_id, version_label, filing_id, effective_date, status,
                created_at, notes)
               VALUES (?, ?, ?, ?, 'analytical', ?, ?)""",
            (v, label, meta["filing_id"], meta["effective_date"],
             utcnow_iso(), meta["notes"]))
        version_id = cur.lastrowid
        for factor, values in sorted(table.items()):
            self.conn.executemany(
                """INSERT INTO rate_factor_values
                   (version_id, factor_name, factor_value, relativity)
                   VALUES (?, ?, ?, ?)""",
                [(version_id, factor, val, rel)
                 for val, rel in sorted(values.items())])
        self.auditor.log(version_id, "version_created", APPROVER_ANALYTICAL,
                         detail=f"{label} analytical build: "
                                f"{sum(len(x) for x in table.values())} factor-values loaded")
        if v == 1:
            for factor in sorted(table):
                self.auditor.log(version_id, "rate_load", APPROVER_ANALYTICAL,
                                 factor_name=factor, new_value=table[factor],
                                 detail=f"{label} initial load of factor '{factor}'")
        else:
            prev = build_version_table(v - 1)
            for d in diff_tables(prev, table):
                rationale = next((r for f, val, _o, _n, r in meta["deltas"]
                                  if f == d["factor"] and val == d["value"]), "")
                self.auditor.log(
                    version_id, "rate_change", APPROVER_ANALYTICAL,
                    factor_name=d["factor"],
                    old_value=None if d["old"] is None else {"value": d["value"],
                                                             "relativity": d["old"]},
                    new_value={"value": d["value"], "relativity": d["new"]},
                    detail=f"{label} {d['factor']}.{d['value']}: "
                           f"{d['old']} -> {d['new']}. {rationale}")
        self._record_gate(version_id, "analytical",
                          f"{label} analytical build complete",
                          APPROVER_ANALYTICAL, checks_passed=1)
        n_changes = len(meta["deltas"]) if v > 1 else len(table)
        print(f"  analytical: {sum(len(x) for x in table.values())} factor-values, "
              f"{n_changes} change(s) audited")

        # ---- Stage 2: staging / UAT ----------------------------------
        self._set_status(version_id, "staging_uat")
        quotes = generate_quotes(table, QUOTES_PER_VERSION,
                                 seed=GENERATOR_SEED_BASE + v)
        for q in quotes:
            self.conn.execute(
                """INSERT INTO quotes
                   (version_id, species, breed, age_years, zip_code, territory,
                    deductible, reimbursement, annual_limit, discounts,
                    annual_premium, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (version_id, q["species"], q["breed"], q["age_years"],
                 q["zip_code"], _territory(q["zip_code"]),
                 q["deductible"], q["reimbursement"], q["annual_limit"],
                 q["discounts"], q["annual_premium"], utcnow_iso()))
        self.conn.commit()
        checks = run_uat_checks(self.conn, version_id, v, table, quotes)
        for c in checks:
            print(f"  UAT [{'PASS' if c['passed'] else 'FAIL'}] "
                  f"{c['check']}: {c['detail']}")
        assert all(c["passed"] for c in checks), \
            f"{label} failed UAT — promotion blocked (would count as rollback trigger)"
        self.auditor.log(version_id, "uat_passed", APPROVER_UAT,
                         detail=f"{label} UAT: {len(checks)}/{len(checks)} checks passed; "
                                f"{len(quotes)} quotes rated")
        self._record_gate(version_id, "staging_uat",
                          f"{label} UAT sign-off", APPROVER_UAT,
                          checks_passed=len(checks))

        # ---- Stage 3: production -------------------------------------
        self.auditor.log(version_id, "prod_signoff", APPROVER_PROD,
                         detail=f"{label} approved for production deployment")
        self._record_gate(version_id, "production",
                          f"{label} production deployment", APPROVER_PROD,
                          checks_passed=len(checks))
        self._set_status(version_id, "production")
        premiums = [q["annual_premium"] for q in quotes]
        summary_path = self._write_summary(meta, version_id, table, quotes,
                                           premiums, checks)
        print(f"  production: deployed, summary -> {summary_path.name}")
        self.report["versions"].append({
            "version": v, "label": label, "filing_id": meta["filing_id"],
            "effective_date": meta["effective_date"],
            "n_factor_values": sum(len(x) for x in table.values()),
            "n_quotes": len(quotes),
            "premium_min": min(premiums), "premium_median": statistics.median(premiums),
            "premium_max": max(premiums),
            "uat_checks_passed": f"{len(checks)}/{len(checks)}",
            "rollbacks": 0,
            "summary": str(summary_path),
        })

    def _write_summary(self, meta, version_id, table, quotes, premiums,
                       checks) -> Path:
        n_audit = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE version_id = ?",
            (version_id,)).fetchone()["c"]
        gates = self.conn.execute(
            """SELECT stage, gate_name, approver, approved_at
               FROM release_gates WHERE version_id = ? ORDER BY seq""",
            (version_id,)).fetchall()
        changes = ([f"initial load: 8 factors, "
                    f"{sum(len(x) for x in table.values())} factor-values"]
                   if meta["version"] == 1
                   else [f"{f}.{val}: {o} -> {n} — {r}"
                         for f, val, o, n, r in meta["deltas"]])
        lines = [
            f"# Deployment Summary — {meta['label']} (SYNTHETIC DATA)",
            "",
            f"- Filing ID: {meta['filing_id']} (synthetic, SERFF-pattern)",
            f"- Effective date: {meta['effective_date']}",
            f"- Notes: {meta['notes']}",
            "",
            "## Rate changes in this version",
        ]
        lines += [f"- {c}" for c in changes]
        lines += [
            "",
            "## UAT results (staging gate — all must pass before production)",
        ]
        lines += [f"- [{'x' if c['passed'] else ' '}] {c['check']}: {c['detail']}"
                  for c in checks]
        lines += [
            "",
            "## Sign-off gates",
        ]
        lines += [f"- {g['stage']}: {g['gate_name']} — approver `{g['approver']}` "
                  f"at {g['approved_at']}" for g in gates]
        lines += [
            "",
            "## Deployment metrics",
            f"- Quotes rated: {len(quotes)}",
            f"- Annual premium: min ${min(premiums):.2f} / "
            f"median ${statistics.median(premiums):.2f} / max ${max(premiums):.2f}",
            f"- Audit rows for this version: {n_audit}",
            f"- Rollbacks: 0 (promotion gated on passing UAT)",
            "",
            "_Generated by release_pipeline.py. All data synthetic._",
        ]
        path = self.summaries_dir / f"{meta['label']}_deployment_summary.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def _territory(zip_code: str) -> str:
    from .rating_engine import territory_for_zip
    return territory_for_zip(zip_code)


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Run the 6-version pet-insurance rate release pipeline.")
    ap.add_argument("--db", default=str(ROOT / "data" / "pet_rating.db"))
    ap.add_argument("--summaries",
                    default=str(ROOT / "outputs" / "deployment_summaries"))
    args = ap.parse_args()
    pipeline = ReleasePipeline(args.db, args.summaries)
    report = pipeline.run()
    out = ROOT / "outputs" / "run_report.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nRun report -> {out}")


if __name__ == "__main__":
    main()
