"""Pet insurance rating engine.

Multiplicative relativity model over EXACTLY 8 rating factors:

    annual_premium = base_rate(species)
                     x f(breed) x f(age band) x f(territory)
                     x f(deductible) x f(reimbursement) x f(annual_limit)
                     x f(discounts, combined multiplicatively)

The engine is a pure function of (policy, rate_table): no randomness, no
wall-clock reads, no hidden state — identical inputs always produce an
identical premium (asserted by the test suite).

ALL DATA SYNTHETIC.
"""

from typing import Dict, List

# ---------------------------------------------------------------------------
# The 8 rating factors. This list is the single source of truth; the generator,
# the rate-table builder, the UAT checks and the tests all derive from it.
# ---------------------------------------------------------------------------
RATING_FACTORS: List[str] = [
    "species",
    "breed",
    "age",
    "territory",
    "deductible",
    "reimbursement",
    "annual_limit",
    "discounts",
]

# Annual base rates by species (USD / year). The species factor is exercised
# through base-rate selection; its table relativity is 1.0 by construction.
BASE_RATES: Dict[str, float] = {
    "dog": 480.0,
    "cat": 300.0,
}

# Synthetic ZIP -> territory map. ZIPs are invented for this project.
TERRITORY_ZIPS: Dict[str, List[str]] = {
    "urban_core": ["60601", "60602", "60603", "60604"],
    "urban":      ["60605", "60606", "60607", "60608"],
    "suburban":   ["60101", "60102", "60103", "60104"],
    "small_town": ["62501", "62502", "62503", "62504"],
    "rural":      ["62601", "62602", "62603", "62604"],
}
ZIP_TO_TERRITORY: Dict[str, str] = {
    z: t for t, zs in TERRITORY_ZIPS.items() for z in zs
}

DOG_BREEDS = [
    "labrador_retriever", "french_bulldog", "german_shepherd",
    "golden_retriever", "mixed_breed_dog",
]
CAT_BREEDS = [
    "domestic_shorthair", "siamese", "maine_coon",
    "persian", "mixed_breed_cat",
]
BREED_TO_SPECIES = {b: "dog" for b in DOG_BREEDS} | {b: "cat" for b in CAT_BREEDS}


def age_band(age_years: float) -> str:
    """Map a pet's age to the rated age band."""
    if age_years < 0:
        raise ValueError(f"age_years must be >= 0, got {age_years}")
    if age_years < 1:
        return "under_1"
    if age_years <= 5:
        return "1_to_5"
    if age_years <= 9:
        return "6_to_9"
    return "10_plus"


def territory_for_zip(zip_code: str) -> str:
    """Map a ZIP code to its rating territory."""
    try:
        return ZIP_TO_TERRITORY[zip_code]
    except KeyError:
        raise ValueError(f"unknown ZIP code {zip_code!r}") from None


def _rel(rate_table: Dict[str, Dict[str, float]], factor: str, value: str) -> float:
    try:
        return rate_table[factor][value]
    except KeyError:
        raise ValueError(
            f"rate table has no relativity for factor={factor!r} value={value!r}"
        ) from None


def rate_premium(policy: Dict, rate_table: Dict[str, Dict[str, float]]) -> float:
    """Rate one policy. `policy` must carry all 8 rating factors.

    policy keys: species, breed, age_years, zip_code, deductible (int),
                reimbursement (int), annual_limit (str), discounts (list[str])
    rate_table: {factor: {value: relativity}}, all values keyed as strings
                except where noted below.
    """
    missing = [f for f in ("species", "breed", "age_years", "zip_code",
                           "deductible", "reimbursement", "annual_limit",
                           "discounts") if f not in policy]
    if missing:
        raise ValueError(f"policy missing rating inputs: {missing}")

    species = policy["species"]
    if species not in BASE_RATES:
        raise ValueError(f"unknown species {species!r}")
    breed = policy["breed"]
    if BREED_TO_SPECIES.get(breed) != species:
        raise ValueError(f"breed {breed!r} is not a {species} breed")

    premium = BASE_RATES[species]
    premium *= _rel(rate_table, "species", species)
    premium *= _rel(rate_table, "breed", breed)
    premium *= _rel(rate_table, "age", age_band(policy["age_years"]))
    premium *= _rel(rate_table, "territory",
                    territory_for_zip(policy["zip_code"]))
    premium *= _rel(rate_table, "deductible", str(policy["deductible"]))
    premium *= _rel(rate_table, "reimbursement", str(policy["reimbursement"]))
    premium *= _rel(rate_table, "annual_limit", policy["annual_limit"])

    discount_factor = 1.0
    for code in policy["discounts"]:
        discount_factor *= _rel(rate_table, "discounts", code)
    premium *= discount_factor

    return round(premium, 2)


def factor_value_count(rate_table: Dict[str, Dict[str, float]]) -> Dict[str, int]:
    """How many rated values each of the 8 factors has in a rate table."""
    return {f: len(rate_table.get(f, {})) for f in RATING_FACTORS}
