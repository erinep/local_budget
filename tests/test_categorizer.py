"""Categorizer v1 vs v2 accuracy harness.

Runs the labeled fixture set through both categorizers and prints a baseline
comparison. The harness uses only aliases (no past_transactions corpus) to
measure cold-start accuracy — the realistic state for a new user.

Run: pytest tests/test_categorizer.py -v -s
"""
import json
from pathlib import Path
import pytest
from app.transactions.services import (
    make_categorizer_v1,
    make_categorizer_v2,
    normalize_description,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "categorizer_labeled.json"


def load_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _seed_aliases() -> list[tuple[str, str]]:
    """Load the seed corpus as (normalized_name, category_name) pairs."""
    seed_path = (
        Path(__file__).parent.parent / "app" / "account_settings" / "seed_merchant_aliases.json"
    )
    with open(seed_path, encoding="utf-8") as f:
        data = json.load(f)
    return [(normalize_description(e["normalized_name"]), e["category_name"]) for e in data]


def test_normalize_description():
    cases = [
        # Processor prefixes
        ("SQ * TIM HORTONS", "TIM HORTONS"),
        ("PAYPAL * NETFLIX", "NETFLIX"),
        ("TST* MCDONALDS", "MCDONALDS"),
        ("SP * BESTBUY", "BESTBUY"),
        ("WWW.AMAZON.CA", "AMAZON.CA"),
        # Store number after merchant name
        ("STARBUCKS #1234", "STARBUCKS"),
        # Leading store number
        ("#243 RETAIL STORE TORONTO", "RETAIL STORE TORONTO"),
        # Trailing store number + city
        ("SHELL OIL 001", "SHELL OIL"),
        ("GROCERY STORE 1099 SPRINGFIELD", "GROCERY STORE"),
        ("GAS STATION 00822 OTTAWA", "GAS STATION"),
        # City + province suffix
        ("SUBWAY TORONTO ON", "SUBWAY"),
        # Transaction ID after *
        ("MERCHANT.CA*AB12CD34 MERCHANT.CA", "MERCHANT.CA"),
        ("ONLINE STORE* XY9ZPDQMT MONTREAL", "ONLINE STORE"),
        ("RETAILER*123456789 WWW.RETAILER.CA", "RETAILER"),
        # Short booking code before * with domain after — use domain
        ("BKC*MERCHANT.COM STORE", "MERCHANT.COM"),
        # Alphanumeric code after / (must contain a digit)
        ("TRANSIT CO/RCM5PT8W TORONTO", "TRANSIT CO"),
        ("RAIL SERVICE/KHV7R MONTREAL", "RAIL SERVICE"),
        # Trailing phone number — non-province word after phone must not truncate merchant
        ("SUPPORT LINE 800-555-0100 HELP", "SUPPORT LINE"),
        ("CHARITY ORG TO 800-555-0100", "CHARITY ORG TO"),
        # Case normalisation — same merchant, different input case
        ("Merchant.ca", "MERCHANT.CA"),
        ("MERCHANT.CA", "MERCHANT.CA"),
    ]
    for raw, expected in cases:
        assert normalize_description(raw) == expected, (
            f"normalize_description({raw!r}) != {expected!r}"
        )


def test_categorizer_v2_cold_start_accuracy():
    """v2 with seed aliases only (no past_transactions) must beat or match v1."""
    fixture = load_fixture()
    aliases = _seed_aliases()
    keywords: list[tuple[str, str]] = []
    categorize_v2 = make_categorizer_v2("test-user", keywords, aliases)
    categorize_v1 = make_categorizer_v1({}, {})

    v2_correct = sum(
        1 for item in fixture
        if categorize_v2(item["description"]) == item["expected_category"]
    )
    v1_correct = sum(
        1 for item in fixture
        if categorize_v1(item["description"]) == item["expected_category"]
    )

    total = len(fixture)
    print(f"\nv1 accuracy (cold start): {v1_correct}/{total} = {v1_correct/total:.0%}")
    print(f"v2 accuracy (cold start): {v2_correct}/{total} = {v2_correct/total:.0%}")

    assert v2_correct >= v1_correct, (
        f"v2 ({v2_correct}/{total}) must not be worse than v1 ({v1_correct}/{total})"
    )
