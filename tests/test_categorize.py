"""Tests for the categorization service.

Uses make_categorizer directly (ADR 0005). No monkeypatching of globals —
the globals were removed in the Phase 0 refactor and monkeypatch calls on them
would silently become no-ops and mask broken tests.
"""

from app.transactions.services import make_categorizer


# Helpers: factories for tests that need specific map contents.
def _generic_only(generic_map):
    return make_categorizer({}, generic_map)


def _with_custom(custom_map, generic_map):
    return make_categorizer(custom_map, generic_map)


# Load the real generic map once so keyword-match tests exercise the actual data.
import json, os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_REPO_ROOT, "generic_categories.json")) as _f:
    _GENERIC_MAP = json.load(_f)


def test_generic_keyword_match():
    fn = _generic_only(_GENERIC_MAP)
    assert fn("TIM HORTONS") == "Food"


def test_case_insensitive():
    fn = _generic_only(_GENERIC_MAP)
    assert fn("tim hortons") == "Food"


def test_substring_match():
    # "RESTAURANT" is a substring keyword — any merchant containing it matches
    fn = _generic_only(_GENERIC_MAP)
    assert fn("SOME RANDOM RESTAURANT") == "Food"


def test_custom_rule_beats_generic():
    fn = _with_custom({"CustomCategory": ["TESTMART"]}, {"GenericCategory": ["TESTMART"]})
    assert fn("TESTMART") == "CustomCategory"


def test_unmatched_falls_back_to_slush_fund():
    fn = _generic_only(_GENERIC_MAP)
    assert fn("TOTALLY UNKNOWN MERCHANT XYZ") == "Slush Fund"


def test_nan_string_handled():
    # pandas can produce "nan" strings from empty cells
    fn = _generic_only(_GENERIC_MAP)
    assert fn("nan") == "Slush Fund"


def test_transport_keyword():
    fn = _generic_only(_GENERIC_MAP)
    assert fn("UBER") == "Transport"


def test_utilities_keyword():
    fn = _generic_only(_GENERIC_MAP)
    assert fn("ROGERS WIRELESS") == "Utilities"


def test_travel_keyword():
    fn = _generic_only(_GENERIC_MAP)
    assert fn("AIRBNB") == "Travel"
