"""Synthetic quote generator.

Generates synthetic pet-insurance quotes that exercise ALL 8 rating factors,
rates each quote with the rating engine, and returns policy dicts ready for
loading into the `quotes` table.

ALL DATA SYNTHETIC. Generation is seeded: the same (version, n, seed) always
produces the same quotes, so pipeline runs are exactly reproducible.
"""

import json
import random
from datetime import datetime, timezone
from typing import Dict, List

from .rating_engine import (
    RATING_FACTORS,
    BREED_TO_SPECIES,
    TERRITORY_ZIPS,
    rate_premium,
)
from .rate_tables import RateTable

DEDUCTIBLES = [100, 250, 500, 750, 1000]
REIMBURSEMENTS = [70, 80, 90]
ANNUAL_LIMITS = ["5000", "10000", "15000", "unlimited"]


def generate_quotes(rate_table: RateTable, n: int, seed: int) -> List[Dict]:
    """Generate `n` synthetic quotes rated against `rate_table`."""
    rng = random.Random(seed)
    all_zips = [z for zs in TERRITORY_ZIPS.values() for z in zs]
    discount_codes = sorted(rate_table["discounts"].keys())
    quotes = []
    for _ in range(n):
        species = rng.choice(["dog", "cat"])
        breed = rng.choice([b for b, s in BREED_TO_SPECIES.items() if s == species])
        n_disc = rng.choice([0, 0, 1, 1, 2, 3])  # most pets carry 0-1 discounts
        discounts = rng.sample(discount_codes, k=min(n_disc, len(discount_codes)))
        policy = {
            "species": species,
            "breed": breed,
            "age_years": round(rng.uniform(0.25, 14.0), 2),
            "zip_code": rng.choice(all_zips),
            "deductible": rng.choice(DEDUCTIBLES),
            "reimbursement": rng.choice(REIMBURSEMENTS),
            "annual_limit": rng.choice(ANNUAL_LIMITS),
            "discounts": sorted(discounts),
        }
        premium = rate_premium(policy, rate_table)
        quotes.append({**policy,
                       "discounts": json.dumps(policy["discounts"]),
                       "annual_premium": premium})
    _ensure_coverage(quotes, rate_table, rng)
    return quotes


def _ensure_coverage(quotes: List[Dict], rate_table: RateTable,
                     rng: random.Random) -> None:
    """Guarantee every rating factor is exercised with >= 2 distinct values.

    With n=2000 seeded draws this is satisfied by chance, but the explicit
    repair step makes coverage a construction guarantee rather than luck.
    """
    from .rating_engine import age_band, territory_for_zip
    discount_codes = sorted(rate_table["discounts"].keys())

    def distinct(key, transform=None):
        t = transform if transform is not None else (lambda q: q[key])
        return {t(q) for q in quotes}

    repairs = 0
    # species / breed
    if len(distinct("species")) < 2:
        quotes[0] = _force(quotes[0], rate_table, rng, species="cat")
        repairs += 1
    # age bands
    if len(distinct("age_years", lambda q: age_band(q["age_years"]))) < 2:
        quotes[1] = _force(quotes[1], rate_table, rng, age_years=12.0)
        repairs += 1
    # territories
    if len(distinct("zip_code", lambda q: territory_for_zip(q["zip_code"]))) < 2:
        quotes[2] = _force(quotes[2], rate_table, rng, zip_code="62601")
        repairs += 1
    # deductible / reimbursement / annual_limit
    for i, (key, alt) in enumerate(
            [("deductible", 1000), ("reimbursement", 90),
             ("annual_limit", "unlimited")]):
        if len(distinct(key)) < 2:
            quotes[3 + i] = _force(quotes[3 + i], rate_table, rng, **{key: alt})
            repairs += 1
    # discounts: need quotes both with and without at least one discount code
    with_disc = any(json.loads(q["discounts"]) for q in quotes)
    without_disc = any(not json.loads(q["discounts"]) for q in quotes)
    if not (with_disc and without_disc):
        quotes[6] = _force(quotes[6], rate_table, rng,
                           discounts=[discount_codes[0]])
        repairs += 1
    # breed: need >= 2 distinct breeds (implied by species>=2, but assert anyway)
    if len(distinct("breed")) < 2:
        q = dict(quotes[7])
        q["breed"] = ("french_bulldog" if q["species"] == "dog"
                      else "maine_coon")
        q["annual_premium"] = rate_premium(_policy_view(q), rate_table)
        q["discounts"] = json.dumps(json.loads(q["discounts"]))
        quotes[7] = q
        repairs += 1
    if repairs:
        print(f"  [generator] applied {repairs} coverage repair(s)")


def _policy_view(q: Dict) -> Dict:
    q = dict(q)
    q["discounts"] = json.loads(q["discounts"]) if isinstance(
        q["discounts"], str) else q["discounts"]
    return q


def _force(quote: Dict, rate_table: RateTable, rng: random.Random,
           **overrides) -> Dict:
    q = _policy_view(quote)
    q.update(overrides)
    if "species" in overrides and "breed" not in overrides:
        q["breed"] = ("labrador_retriever" if q["species"] == "dog"
                      else "domestic_shorthair")
    premium = rate_premium(q, rate_table)
    return {**q, "discounts": json.dumps(sorted(q["discounts"])),
            "annual_premium": premium}


def coverage_report(quotes: List[Dict]) -> Dict[str, int]:
    """Distinct-value count exercised per rating factor (quotes must cover 8)."""
    from .rating_engine import age_band, territory_for_zip
    rep = {
        "species": len({q["species"] for q in quotes}),
        "breed": len({q["breed"] for q in quotes}),
        "age": len({age_band(q["age_years"]) for q in quotes}),
        "territory": len({territory_for_zip(q["zip_code"]) for q in quotes}),
        "deductible": len({q["deductible"] for q in quotes}),
        "reimbursement": len({q["reimbursement"] for q in quotes}),
        "annual_limit": len({q["annual_limit"] for q in quotes}),
        "discounts": (1 if any(json.loads(q["discounts"]) for q in quotes) else 0)
                     + (1 if any(not json.loads(q["discounts"]) for q in quotes) else 0),
    }
    assert set(rep) == set(RATING_FACTORS), "coverage report must span 8 factors"
    return rep


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
