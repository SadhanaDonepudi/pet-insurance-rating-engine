"""Test suite — Pet Insurance Rating Engine & Release Pipeline.

Every number asserted here is produced by the repo's own code (seeded and
reproducible): 8 rating factors, 6 pricing versions, 0 rollbacks.
"""

import json
import sqlite3

import pytest

from src.audit import Auditor
from src.data_generator import coverage_report
from src.rate_tables import VERSIONS, build_version_table, diff_tables
from src.rating_engine import RATING_FACTORS, rate_premium
from src.release_pipeline import (
    PREMIUM_MAX,
    PREMIUM_MIN,
    QUOTES_PER_VERSION,
    STAGES,
)


# ---------------------------------------------------------------------------
# 1. Exactly 8 rating factors
# ---------------------------------------------------------------------------
def test_exactly_8_rating_factors(db):
    assert len(RATING_FACTORS) == 8
    rows = db.execute("SELECT DISTINCT factor_name FROM rate_factor_values"
                      ).fetchall()
    in_db = {r["factor_name"] for r in rows}
    assert in_db == set(RATING_FACTORS), f"DB factors: {sorted(in_db)}"


def test_all_8_factors_have_values_every_version(db):
    for v in range(1, 7):
        rows = db.execute(
            """SELECT factor_name, COUNT(*) c FROM rate_factor_values
               WHERE version_id = ? GROUP BY 1""", (v,)).fetchall()
        assert len(rows) == 8, f"v{v} has {len(rows)} factors"
        assert all(r["c"] > 0 for r in rows)


# ---------------------------------------------------------------------------
# 2. Exactly 6 pricing versions
# ---------------------------------------------------------------------------
def test_exactly_6_versions(db):
    n = db.execute("SELECT COUNT(*) c FROM rate_versions").fetchone()["c"]
    assert n == 6


def test_all_versions_reached_production(db):
    statuses = [r["status"] for r in
                db.execute("SELECT status FROM rate_versions ORDER BY version_id")]
    assert statuses == ["production"] * 6


def test_version_tables_match_declared_deltas():
    tables = {m["version"]: build_version_table(m["version"]) for m in VERSIONS}
    assert len(tables) == 6
    # v6 must equal v1 plus every declared delta — nothing more, nothing less
    cumulative = []
    for m in VERSIONS:
        if m["version"] > 1:
            cumulative += diff_tables(tables[m["version"] - 1],
                                      tables[m["version"]])
    declared = [(f, val) for m in VERSIONS for f, val, _o, _n, _r in m["deltas"]]
    assert sorted((d["factor"], d["value"]) for d in cumulative) == sorted(declared)


# ---------------------------------------------------------------------------
# 3. Gate sequence order: analytical -> staging_uat -> production
# ---------------------------------------------------------------------------
def test_gate_sequence_order(db):
    for v in range(1, 7):
        stages = [r["stage"] for r in db.execute(
            """SELECT stage FROM release_gates
               WHERE version_id = ? ORDER BY seq""", (v,))]
        assert stages == STAGES, f"v{v} gate order: {stages}"


def test_each_gate_has_approver_and_timestamp(db):
    rows = db.execute(
        "SELECT approver, approved_at FROM release_gates").fetchall()
    assert len(rows) == 18  # 3 gates x 6 versions
    assert all(r["approver"] and r["approved_at"] for r in rows)


# ---------------------------------------------------------------------------
# 4. Audit completeness: 100% traceability of every rate change
# ---------------------------------------------------------------------------
def test_audit_completeness(db):
    auditor = Auditor(db)
    report = auditor.verify_complete_traceability()
    assert report["traceability_pct"] == 100.0
    assert report["expected_changes"] == 15   # 8 loads + 7 changes
    assert report["surplus_rows"] == 0


def test_audit_row_count_is_33(db):
    # 15 change rows + 18 gate rows (version_created/uat_passed/prod_signoff)
    n = db.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
    assert n == 33


# ---------------------------------------------------------------------------
# 5. Zero rollbacks across all 6 versions
# ---------------------------------------------------------------------------
def test_zero_rollbacks(db):
    n = db.execute(
        "SELECT COUNT(*) c FROM audit_log WHERE change_type = 'rollback'"
    ).fetchone()["c"]
    assert n == 0
    rolled = db.execute(
        "SELECT COUNT(*) c FROM rate_versions WHERE status = 'rolled_back'"
    ).fetchone()["c"]
    assert rolled == 0


# ---------------------------------------------------------------------------
# 6. Engine determinism
# ---------------------------------------------------------------------------
def test_engine_determinism():
    table = build_version_table(6)
    policies = [
        {"species": "dog", "breed": "french_bulldog", "age_years": 11.0,
         "zip_code": "60601", "deductible": 500, "reimbursement": 80,
         "annual_limit": "10000", "discounts": []},
        {"species": "cat", "breed": "maine_coon", "age_years": 0.5,
         "zip_code": "62604", "deductible": 1000, "reimbursement": 90,
         "annual_limit": "unlimited",
         "discounts": ["multi_pet", "wellness_plan", "annual_pay"]},
        {"species": "dog", "breed": "mixed_breed_dog", "age_years": 4.0,
         "zip_code": "60102", "deductible": 250, "reimbursement": 70,
         "annual_limit": "5000", "discounts": ["annual_pay"]},
    ]
    for p in policies:
        first = rate_premium(p, table)
        assert all(rate_premium(p, table) == first for _ in range(10))


def test_known_premium_regression():
    # Hand-computed against the v6 table:
    # 480 x 1.42 (french_bulldog, repriced v4) x 1.75 (10_plus, repriced v2)
    #     x 1.28 (urban_core, repriced v3) x 1.00 x 1.00 x 1.00 x 1.00
    table = build_version_table(6)
    p = {"species": "dog", "breed": "french_bulldog", "age_years": 12.0,
         "zip_code": "60601", "deductible": 500, "reimbursement": 80,
         "annual_limit": "10000", "discounts": []}
    assert rate_premium(p, table) == round(480 * 1.42 * 1.75 * 1.28, 2)


# ---------------------------------------------------------------------------
# 7. Quote coverage + premium bounds (UAT properties hold in the DB)
# ---------------------------------------------------------------------------
def test_quote_factor_coverage_all_versions(db):
    for v in range(1, 7):
        quotes = [dict(r) for r in db.execute(
            "SELECT * FROM quotes WHERE version_id = ?", (v,))]
        assert len(quotes) == QUOTES_PER_VERSION
        cov = coverage_report(quotes)
        assert set(cov) == set(RATING_FACTORS)
        assert all(c >= 2 for c in cov.values()), f"v{v}: {cov}"


def test_premium_bounds_all_quotes(db):
    bad = db.execute(
        """SELECT COUNT(*) c FROM quotes
           WHERE annual_premium < ? OR annual_premium > ?""",
        (PREMIUM_MIN, PREMIUM_MAX)).fetchone()["c"]
    assert bad == 0


# ---------------------------------------------------------------------------
# 8. Deployment summaries: one per version
# ---------------------------------------------------------------------------
def test_six_deployment_summaries(pipeline_run):
    summaries = sorted(pipeline_run["summaries_dir"].glob("*_deployment_summary.md"))
    assert len(summaries) == 6
    for path, meta in zip(summaries, VERSIONS):
        text = path.read_text(encoding="utf-8")
        assert meta["filing_id"] in text
        assert "Rollbacks: 0" in text
