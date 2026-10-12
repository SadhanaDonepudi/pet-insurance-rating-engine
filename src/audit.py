"""Audit logging + verifiability checks.

Every rate-table change, gate sign-off, and (had there been any) rollback is
written to `audit_log` with a global monotonic `seq`. The verifiability
check proves 100% traceability: the set of audited rate changes must exactly
match the set of actual table diffs between consecutive versions.
"""

import json
import sqlite3
from typing import Dict, List

from .data_generator import utcnow_iso
from .rate_tables import RateTable, VERSIONS, build_version_table, diff_tables


class Auditor:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._seq = self._max_seq()

    def _max_seq(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(seq), 0) s FROM audit_log"
                                ).fetchone()
        return row["s"]

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def log(self, version_id: int, change_type: str, approver: str,
            factor_name=None, old_value=None, new_value=None,
            detail: str = "") -> int:
        cur = self.conn.execute(
            """INSERT INTO audit_log
               (version_id, change_type, factor_name, old_value, new_value,
                approver, recorded_at, seq, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (version_id, change_type, factor_name,
             json.dumps(old_value) if old_value is not None else None,
             json.dumps(new_value) if new_value is not None else None,
             approver, utcnow_iso(), self._next_seq(), detail))
        self.conn.commit()
        return cur.lastrowid

    # -- verifiability -----------------------------------------------------
    def verify_complete_traceability(self) -> Dict:
        """Assert audit rows cover 100% of rate-table changes.

        For v1: one `rate_load` row per factor (8).
        For v2..v6: one `rate_change` row per (factor, value) diff vs the
        previous version. Returns a report dict; raises AssertionError on
        any gap or surplus.
        """
        tables = {m["version"]: build_version_table(m["version"])
                  for m in VERSIONS}
        expected: List[Dict] = []
        for m in VERSIONS:
            v = m["version"]
            if v == 1:
                for factor in sorted(tables[1]):
                    expected.append({"version": v, "factor": factor,
                                     "type": "rate_load"})
            else:
                for d in diff_tables(tables[v - 1], tables[v]):
                    expected.append({"version": v, "factor": d["factor"],
                                     "value": d["value"], "type": "rate_change"})
        rows = self.conn.execute(
            """SELECT version_id, change_type, factor_name, new_value
               FROM audit_log
               WHERE change_type IN ('rate_load', 'rate_change')""").fetchall()

        missing, surplus = [], list(rows)
        for e in expected:
            match = None
            for r in surplus:
                if (r["version_id"] == e["version"]
                        and r["change_type"] == e["type"]
                        and r["factor_name"] == e["factor"]):
                    if e["type"] == "rate_load" or (
                            e.get("value")
                            and json.loads(r["new_value"] or "{}").get("value")
                            == e["value"]):
                        match = r
                        break
            if match is None:
                missing.append(e)
            else:
                surplus.remove(match)
        assert not missing, f"unaudited rate changes: {missing}"
        assert not surplus, f"audit rows with no matching change: " \
                            f"{[dict(r) for r in surplus]}"
        return {"expected_changes": len(expected),
                "audited_changes": len(expected) - len(missing),
                "surplus_rows": len(surplus),
                "traceability_pct": 100.0}
