import pytest
from app import categorize


def test_generic_keyword_match():
    assert categorize("TIM HORTONS") == "Food"


def test_case_insensitive():
    assert categorize("tim hortons") == "Food"


def test_substring_match():
    # "RESTAURANT" is a substring keyword — any merchant containing it matches
    assert categorize("SOME RANDOM RESTAURANT") == "Food"


def test_custom_rule_beats_generic(monkeypatch):
    # Patch both maps with controlled values so this test doesn't depend on
    # custom_categories.json being present (it's personal and not committed)
    monkeypatch.setattr("app.CUSTOM_CATEGORY_MAP", {"CustomCategory": ["TESTMART"]})
    monkeypatch.setattr("app.GENERIC_CATEGORY_MAP", {"GenericCategory": ["TESTMART"]})
    assert categorize("TESTMART") == "CustomCategory"


def test_unmatched_falls_back_to_slush_fund():
    assert categorize("TOTALLY UNKNOWN MERCHANT XYZ") == "Slush Fund"


def test_nan_string_handled():
    # pandas can produce "nan" strings from empty cells
    assert categorize("nan") == "Slush Fund"


def test_transport_keyword():
    assert categorize("UBER") == "Transport"


def test_utilities_keyword():
    assert categorize("ROGERS WIRELESS") == "Utilities"


def test_travel_keyword():
    assert categorize("AIRBNB") == "Travel"
