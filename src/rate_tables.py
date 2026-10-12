"""Versioned rate tables.

Six pricing versions (v1..v6), modeled on the *public pattern* of a SERFF
rate filing (versioned tables, effective dates, filing IDs). Every filing ID,
rate, and date here is SYNTHETIC — this is not a real filing.

Each version's table is a dict {factor: {value: relativity}} covering exactly
the 8 rating factors. Versions are built incrementally: v(n) = v(n-1) + deltas,
and every delta is recorded in the audit log by the release pipeline.
"""

import copy
from typing import Dict, List

RateTable = Dict[str, Dict[str, float]]

# ---------------------------------------------------------------------------
# v1 — initial synthetic filing
# ---------------------------------------------------------------------------
V1_TABLE: RateTable = {
    "species": {
        "dog": 1.0,
        "cat": 1.0,  # species priced via base rate; relativity held at 1.0
    },
    "breed": {
        "labrador_retriever": 1.00,
        "french_bulldog": 1.35,
        "german_shepherd": 1.18,
        "golden_retriever": 1.05,
        "mixed_breed_dog": 0.85,
        "domestic_shorthair": 0.95,
        "siamese": 1.02,
        "maine_coon": 1.12,
        "persian": 1.20,
        "mixed_breed_cat": 0.88,
    },
    "age": {
        "under_1": 0.90,
        "1_to_5": 1.00,
        "6_to_9": 1.25,
        "10_plus": 1.60,
    },
    "territory": {
        "urban_core": 1.20,
        "urban": 1.10,
        "suburban": 1.00,
        "small_town": 0.92,
        "rural": 0.85,
    },
    "deductible": {
        "100": 1.35,
        "250": 1.15,
        "500": 1.00,
        "750": 0.90,
        "1000": 0.82,
    },
    "reimbursement": {
        "70": 0.88,
        "80": 1.00,
        "90": 1.15,
    },
    "annual_limit": {
        "5000": 0.90,
        "10000": 1.00,
        "15000": 1.08,
        "unlimited": 1.20,
    },
    "discounts": {
        "multi_pet": 0.95,
        "wellness_plan": 0.97,
    },
}

# ---------------------------------------------------------------------------
# Version metadata + deltas. Each delta: (factor, value, old, new, rationale).
# ---------------------------------------------------------------------------
VERSIONS: List[Dict] = [
    {
        "version": 1,
        "label": "v1",
        "filing_id": "SERFF-SYN-2024-001",
        "effective_date": "2024-01-01",
        "notes": "Initial synthetic filing: full 8-factor table load.",
        "deltas": [],
    },
    {
        "version": 2,
        "label": "v2",
        "filing_id": "SERFF-SYN-2024-002",
        "effective_date": "2024-04-01",
        "notes": "Senior-pet age-band trend update.",
        "deltas": [
            ("age", "10_plus", 1.60, 1.75,
             "Senior (10+) vet-cost trend +9.4% observed in synthetic experience data"),
        ],
    },
    {
        "version": 3,
        "label": "v3",
        "filing_id": "SERFF-SYN-2024-003",
        "effective_date": "2024-07-01",
        "notes": "Urban-core territory re-tiering.",
        "deltas": [
            ("territory", "urban_core", 1.20, 1.28,
             "Urban-core severity re-tiered on synthetic claim data"),
        ],
    },
    {
        "version": 4,
        "label": "v4",
        "filing_id": "SERFF-SYN-2024-004",
        "effective_date": "2024-10-01",
        "notes": "Breed relativity refresh (brachycephalic breeds).",
        "deltas": [
            ("breed", "french_bulldog", 1.35, 1.42,
             "French Bulldog respiratory-claim frequency update"),
        ],
    },
    {
        "version": 5,
        "label": "v5",
        "filing_id": "SERFF-SYN-2025-001",
        "effective_date": "2025-01-01",
        "notes": "New annual-pay discount; low-deductible curve tweak.",
        "deltas": [
            ("discounts", "annual_pay", None, 0.98,
             "New discount: 2% for annual (vs monthly) premium payment"),
            ("deductible", "100", 1.35, 1.38,
             "$100 deductible anti-selection loading"),
        ],
    },
    {
        "version": 6,
        "label": "v6",
        "filing_id": "SERFF-SYN-2025-002",
        "effective_date": "2025-04-01",
        "notes": "High-reimbursement / unlimited-limit repricing.",
        "deltas": [
            ("reimbursement", "90", 1.15, 1.18,
             "90% reimbursement tier loss-ratio correction"),
            ("annual_limit", "unlimited", 1.20, 1.24,
             "Unlimited annual limit tail-risk loading"),
        ],
    },
]


def build_version_table(version: int) -> RateTable:
    """Build the full rate table for a version by applying deltas to v1."""
    if not 1 <= version <= 6:
        raise ValueError(f"version must be 1..6, got {version}")
    table = copy.deepcopy(V1_TABLE)
    for meta in VERSIONS:
        if meta["version"] > version:
            break
        for factor, value, _old, new, _rationale in meta["deltas"]:
            table[factor][value] = new
    return table


def all_version_tables() -> Dict[int, RateTable]:
    return {m["version"]: build_version_table(m["version"]) for m in VERSIONS}


def diff_tables(old: RateTable, new: RateTable) -> List[Dict]:
    """Return the list of (factor, value, old, new) differences between tables."""
    diffs = []
    for factor in sorted(set(old) | set(new)):
        for value in sorted(set(old.get(factor, {})) | set(new.get(factor, {}))):
            o, n = old.get(factor, {}).get(value), new.get(factor, {}).get(value)
            if o != n:
                diffs.append({"factor": factor, "value": value,
                              "old": o, "new": n})
    return diffs
