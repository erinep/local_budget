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
        ("SQ * TIM HORTONS", "TIM HORTONS"),
        ("PAYPAL * NETFLIX", "NETFLIX"),
        ("TST* MCDONALDS", "MCDONALDS"),
        ("STARBUCKS #1234", "STARBUCKS"),
        ("SUBWAY TORONTO ON", "SUBWAY"),
        ("SP * BESTBUY", "BESTBUY"),
        ("WWW.AMAZON.CA", "AMAZON.CA"),
        ("SHELL OIL 001", "SHELL OIL"),
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
    past: list[tuple[str, str]] = []

    categorize_v2 = make_categorizer_v2("test-user", keywords, aliases, past)
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
