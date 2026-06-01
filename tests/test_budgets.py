"""Contract tests for the Budgeting Module — service layer and routes (ADR-0025).

Contract source: ADR-0025 — Budgeting Module Schema, Service API, and Route Design.

Four sections:

1. Type invariants (no DB required):
     BudgetStatus, Budget, BudgetProgress, ProposedBudget

2. Service logic (no DB required, pure logic via mock):
     get_budget_progress join/variance/status logic
     upsert_budget validation (pre-DB guards)
     apply_proposed_budgets short-circuit on empty

3. Route tests (unit, mocked service, no DATABASE_URL required):
     GET  /budgets/             budget_progress
     GET  /budgets/configure    configure_budgets
     POST /budgets/configure    save_budget
     POST /budgets/<id>/delete  delete_budget_route
     GET  /budgets/propose      propose_budget_preview
     POST /budgets/propose      apply_proposed_budgets_route

4. DB-gated service tests (skipped without DATABASE_URL):
     get_budgets, upsert_budget, delete_budget,
     get_budget_progress, apply_proposed_budgets
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from decimal import Decimal
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# DB-gated skip marker
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

requires_db = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL must be set to run DB-gated budgeting module tests",
)

# ---------------------------------------------------------------------------
# Public API imports
# ---------------------------------------------------------------------------

from app.budgets.services import (
    Budget,
    BudgetProgress,
    BudgetStatus,
    ProposedBudget,
    apply_proposed_budgets,
    delete_budget,
    get_budget_progress,
    get_budgets,
    propose_budgets,
    upsert_budget,
)

# ---------------------------------------------------------------------------
# Shared constants for route and service tests
# ---------------------------------------------------------------------------

_USER_ID = "00000000-0000-0000-0000-000000000001"
_CAT_ID_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_CAT_ID_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_BUDGET_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")

_BUDGET_A = Budget(
    id=_BUDGET_ID,
    user_id=_USER_ID,
    category_id=_CAT_ID_A,
    category_name="Groceries",
    amount=Decimal("500.00"),
)

_PROGRESS_A = BudgetProgress(
    budget=_BUDGET_A,
    category_id=_CAT_ID_A,
    category_name="Groceries",
    target=Decimal("500.00"),
    actual=Decimal("300.00"),
    variance=Decimal("200.00"),
    pct_used=Decimal("60"),
    status=BudgetStatus.UNDER,
)

_PROPOSED_A = ProposedBudget(
    category_id=_CAT_ID_A,
    category_name="Groceries",
    proposed_amount=Decimal("450"),
    months_of_data=3,
    average_monthly_spend=Decimal("450.00"),
)

# ---------------------------------------------------------------------------
# Mock patch paths
# ---------------------------------------------------------------------------

_GET_BUDGET_PROGRESS = "app.budgets.routes.get_budget_progress"
_GET_BUDGETS = "app.budgets.routes.get_budgets"
_PROPOSE_BUDGETS = "app.budgets.routes.propose_budgets"
_UPSERT_BUDGET = "app.budgets.routes.upsert_budget"
_DELETE_BUDGET = "app.budgets.routes.delete_budget"
_APPLY_PROPOSED = "app.budgets.routes.apply_proposed_budgets"
_LIST_CATEGORIES = "app.budgets.routes.list_categories"
_GET_USER_SETTINGS = "app.budgets.routes.get_user_settings"


def _stub_user_settings(user_id: str = ""):
    from app.account_settings.services import UserSettings
    return UserSettings(user_id=user_id or _USER_ID, monthly_income=None)


# ===========================================================================
# Section 1 — Type invariants (no DB required)
# ===========================================================================


class TestBudgetStatusType:
    """BudgetStatus must be an Enum with the three mandated values (ADR-0025)."""

    def test_is_enum(self):
        # Behavior: BudgetStatus is an Enum subclass
        assert issubclass(BudgetStatus, Enum)

    def test_has_under_value(self):
        # Behavior: UNDER member exists
        assert BudgetStatus.UNDER is not None

    def test_has_near_value(self):
        # Behavior: NEAR member exists
        assert BudgetStatus.NEAR is not None

    def test_has_over_value(self):
        # Behavior: OVER member exists
        assert BudgetStatus.OVER is not None

    def test_exactly_three_members(self):
        # Behavior: no undocumented extra values sneak into the enum
        assert set(BudgetStatus) == {BudgetStatus.UNDER, BudgetStatus.NEAR, BudgetStatus.OVER}


class TestBudgetType:
    """Budget must be a frozen dataclass with the documented fields (ADR-0025)."""

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(Budget)

    def test_is_frozen(self):
        # Behavior: frozen=True means instances are immutable
        assert Budget.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_has_required_fields(self):
        # Behavior: all five documented fields present, nothing more or less
        field_names = {f.name for f in dataclasses.fields(Budget)}
        assert field_names == {
            "id",
            "user_id",
            "category_id",
            "category_name",
            "amount",
        }

    def test_is_immutable(self):
        # Behavior: assignment to a frozen dataclass field raises
        b = Budget(
            id=uuid.uuid4(),
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Test",
            amount=Decimal("100.00"),
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            b.amount = Decimal("200.00")  # type: ignore[misc]


class TestBudgetProgressType:
    """BudgetProgress must be a frozen dataclass with the documented fields (ADR-0025)."""

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(BudgetProgress)

    def test_is_frozen(self):
        assert BudgetProgress.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_has_required_fields(self):
        # Behavior: all eight documented fields present
        field_names = {f.name for f in dataclasses.fields(BudgetProgress)}
        assert field_names == {
            "budget",
            "category_id",
            "category_name",
            "target",
            "actual",
            "variance",
            "pct_used",
            "status",
        }

    def test_is_immutable(self):
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            _PROGRESS_A.actual = Decimal("999")  # type: ignore[misc]


class TestProposedBudgetType:
    """ProposedBudget must be a frozen dataclass with the documented fields (ADR-0025)."""

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ProposedBudget)

    def test_is_frozen(self):
        assert ProposedBudget.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_has_required_fields(self):
        # Behavior: all five documented fields present
        field_names = {f.name for f in dataclasses.fields(ProposedBudget)}
        assert field_names == {
            "category_id",
            "category_name",
            "proposed_amount",
            "months_of_data",
            "average_monthly_spend",
        }

    def test_is_immutable(self):
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            _PROPOSED_A.proposed_amount = Decimal("0")  # type: ignore[misc]


# ===========================================================================
# Section 2 — Service logic (no DB required, pure logic tests)
# ===========================================================================

# Patch paths for service-layer tests (the service imports these internally)
# get_spend_by_category is imported locally inside get_budget_progress via
# `from app.transactions.services import ...`, so we patch at the source module.
_SVC_GET_SPEND = "app.transactions.services.get_spend_by_category"
# get_budgets is a module-level function called directly; patch at source.
_SVC_GET_BUDGETS = "app.budgets.services.get_budgets"


def _make_category_spend(category_id, category_name, spend):
    """Build a CategorySpend-like object using a simple namespace."""
    from app.transactions.services import CategorySpend
    return CategorySpend(
        category_id=category_id,
        category_name=category_name,
        spend=Decimal(str(spend)),
        transaction_count=1,
    )


class TestGetBudgetProgressJoinLogic:
    """get_budget_progress join logic — mocked Transaction Engine (ADR-0025, Decision 6)."""

    def _run(self, budgets, spend_rows):
        """Helper: patch both data sources, call get_budget_progress."""
        with (
            patch(_SVC_GET_BUDGETS, return_value=budgets),
            patch(_SVC_GET_SPEND, return_value=spend_rows),
        ):
            return get_budget_progress(_USER_ID, 2026, 5)

    def test_category_with_budget_and_spend(self):
        # Behavior: row appears; target, actual, variance are all correct
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Groceries",
            amount=Decimal("500.00"),
        )
        spend = _make_category_spend(_CAT_ID_A, "Groceries", "300.00")
        result = self._run([budget], [spend])

        assert len(result) == 1
        row = result[0]
        assert row.category_id == _CAT_ID_A
        assert row.target == Decimal("500.00")
        assert row.actual == Decimal("300.00")
        assert row.variance == Decimal("200.00")

    def test_category_with_budget_but_no_spend(self):
        # Behavior: actual=0, status=UNDER (500 > 0, ratio=0 < 0.80)
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Groceries",
            amount=Decimal("500.00"),
        )
        result = self._run([budget], [])

        assert len(result) == 1
        row = result[0]
        assert row.actual == Decimal("0")
        assert row.status == BudgetStatus.UNDER

    def test_category_with_spend_but_no_budget(self):
        # Behavior: appears with target=0, status=OVER (spend > 0, target == 0)
        spend = _make_category_spend(_CAT_ID_B, "Dining", "150.00")
        result = self._run([], [spend])

        assert len(result) == 1
        row = result[0]
        assert row.target == Decimal("0")
        assert row.status == BudgetStatus.OVER

    def test_budget_amount_zero_with_spend_is_over(self):
        # Behavior: target==0, spend>0 → OVER (prevents divide-by-zero, ADR-0025 D8)
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Misc",
            amount=Decimal("0"),
        )
        spend = _make_category_spend(_CAT_ID_A, "Misc", "10.00")
        result = self._run([budget], [spend])

        assert len(result) == 1
        assert result[0].status == BudgetStatus.OVER

    def test_budget_amount_zero_no_spend_is_under(self):
        # Behavior: target==0, spend==0 → UNDER
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Misc",
            amount=Decimal("0"),
        )
        result = self._run([budget], [])

        assert len(result) == 1
        assert result[0].status == BudgetStatus.UNDER

    def test_status_under_below_80_percent(self):
        # Behavior: spend < 80% of target → UNDER
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Groceries",
            amount=Decimal("100.00"),
        )
        # 79% spend
        spend = _make_category_spend(_CAT_ID_A, "Groceries", "79.00")
        result = self._run([budget], [spend])

        assert result[0].status == BudgetStatus.UNDER

    def test_status_near_at_80_percent(self):
        # Behavior: spend == 80% of target → NEAR (boundary)
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Groceries",
            amount=Decimal("100.00"),
        )
        spend = _make_category_spend(_CAT_ID_A, "Groceries", "80.00")
        result = self._run([budget], [spend])

        assert result[0].status == BudgetStatus.NEAR

    def test_status_near_at_100_percent(self):
        # Behavior: spend == 100% of target → NEAR (upper boundary, not yet OVER)
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Groceries",
            amount=Decimal("100.00"),
        )
        spend = _make_category_spend(_CAT_ID_A, "Groceries", "100.00")
        result = self._run([budget], [spend])

        assert result[0].status == BudgetStatus.NEAR

    def test_status_over_above_100_percent(self):
        # Behavior: spend > 100% of target → OVER
        budget = Budget(
            id=_BUDGET_ID,
            user_id=_USER_ID,
            category_id=_CAT_ID_A,
            category_name="Groceries",
            amount=Decimal("100.00"),
        )
        spend = _make_category_spend(_CAT_ID_A, "Groceries", "100.01")
        result = self._run([budget], [spend])

        assert result[0].status == BudgetStatus.OVER

    def test_empty_budgets_and_empty_spend_returns_empty_list(self):
        # Behavior: no data → [] (never raises)
        result = self._run([], [])

        assert result == []


class TestUpsertBudgetValidation:
    """upsert_budget raises ValueError before touching the DB on invalid inputs (ADR-0026)."""

    def _call(self, amount):
        """Attempt upsert with a mocked DB call that should never fire."""
        with patch("app.budgets.services.get_engine") as mock_engine:
            return upsert_budget(_USER_ID, _CAT_ID_A, amount)

    def test_negative_amount_raises_value_error(self):
        # Behavior: amount < 0 → ValueError before any DB call
        with pytest.raises(ValueError):
            self._call(Decimal("-0.01"))


class TestApplyProposedBudgetsLogic:
    """apply_proposed_budgets short-circuits on empty proposals (ADR-0026, error model)."""

    def test_empty_proposals_returns_zero_immediately(self):
        # Behavior: no DB call, returns 0 when proposals list is empty
        mock_engine = MagicMock()
        with patch("app.budgets.services.get_engine", return_value=mock_engine):
            result = apply_proposed_budgets(_USER_ID, [])
        assert result == 0
        # No connection should have been established
        mock_engine.begin.assert_not_called()


# ===========================================================================
# Section 3 — Route tests (unit, mocked service, no DATABASE_URL required)
# ===========================================================================


class TestBudgetProgressRoute:
    """GET /budgets/ — auth gate, defaults, query param forwarding, data rendering."""

    def test_unauthenticated_redirects_to_login(self, client):
        # Behavior: unauthenticated request → 302 to /auth/login
        response = client.get("/budgets/", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        # Behavior: authenticated request → 200
        with (
            patch(_GET_BUDGET_PROGRESS, return_value=[]),
            patch(_GET_BUDGETS, return_value=[]),
            patch(_GET_USER_SETTINGS, side_effect=_stub_user_settings),
            patch(_LIST_CATEGORIES, return_value=[]),
        ):
            response = authenticated_client.get("/budgets/")
        assert response.status_code == 200

    def test_renders_budget_progress_data(self, authenticated_client):
        # Behavior: category name from mocked progress appears in rendered HTML.
        # list_categories must include the matching category so _build_rows picks it up.
        matching_cat = {"id": str(_CAT_ID_A), "name": "Groceries", "keywords": []}
        with (
            patch(_GET_BUDGET_PROGRESS, return_value=[_PROGRESS_A]),
            patch(_GET_BUDGETS, return_value=[]),
            patch(_GET_USER_SETTINGS, side_effect=_stub_user_settings),
            patch(_LIST_CATEGORIES, return_value=[matching_cat]),
        ):
            response = authenticated_client.get("/budgets/")
        assert b"Groceries" in response.data

    def test_defaults_to_current_month_no_query_params(self, authenticated_client):
        # Behavior: no ?year=&month= → service called without aborting
        mock_progress = MagicMock(return_value=[])
        with (
            patch(_GET_BUDGET_PROGRESS, mock_progress),
            patch(_GET_BUDGETS, return_value=[]),
            patch(_GET_USER_SETTINGS, side_effect=_stub_user_settings),
            patch(_LIST_CATEGORIES, return_value=[]),
        ):
            response = authenticated_client.get("/budgets/")
        assert response.status_code == 200
        mock_progress.assert_called_once()
        call_args = mock_progress.call_args[0]
        assert isinstance(call_args[1], int)  # year
        assert isinstance(call_args[2], int)  # month

    def test_accepts_year_and_month_query_params(self, authenticated_client):
        # Behavior: ?year=2026&month=3 passed through to service correctly
        mock_progress = MagicMock(return_value=[])
        with (
            patch(_GET_BUDGET_PROGRESS, mock_progress),
            patch(_GET_BUDGETS, return_value=[]),
            patch(_GET_USER_SETTINGS, side_effect=_stub_user_settings),
            patch(_LIST_CATEGORIES, return_value=[]),
        ):
            response = authenticated_client.get("/budgets/?year=2026&month=3")
        assert response.status_code == 200
        call_args = mock_progress.call_args[0]
        assert call_args[1] == 2026
        assert call_args[2] == 3


class TestSaveAllBudgetsRoute:
    """POST /budgets/save — batch-save all targets, auth gate, success redirect."""

    _VALID_FORM = {f"amount_{_CAT_ID_A}": "500"}

    def test_unauthenticated_redirects(self, client):
        # Behavior: unauthenticated → 302
        response = client.post("/budgets/save", data=self._VALID_FORM, follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_valid_form_redirects_to_budget_progress(self, authenticated_client):
        # Behavior: valid batch submit → 302 to /budgets/
        with (
            patch(_GET_BUDGETS, return_value=[]),
            patch(_UPSERT_BUDGET, return_value=_BUDGET_A),
        ):
            response = authenticated_client.post(
                "/budgets/save",
                data=self._VALID_FORM,
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "/budgets/" in response.headers.get("Location", "")


class TestProposeBudgetPreviewRoute:
    """GET /budgets/propose — auth gate, 200 for authenticated."""

    def test_unauthenticated_redirects(self, client):
        # Behavior: unauthenticated → 302
        response = client.get("/budgets/propose", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        # Behavior: authenticated → 200
        with patch(_PROPOSE_BUDGETS, return_value=[]):
            response = authenticated_client.get("/budgets/propose")
        assert response.status_code == 200


class TestApplyProposedBudgetsRoute:
    """POST /budgets/propose — auth gate, success redirect with flash."""

    _VALID_FORM = {"year": "2026", "month": "5", "replace_existing": "false"}

    def test_unauthenticated_redirects(self, client):
        # Behavior: unauthenticated → 302
        response = client.post(
            "/budgets/propose",
            data=self._VALID_FORM,
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_valid_apply_redirects_to_budget_progress(self, authenticated_client):
        # Behavior: valid apply → 302 to /budgets/
        with (
            patch(_PROPOSE_BUDGETS, return_value=[_PROPOSED_A]),
            patch(_APPLY_PROPOSED, return_value=1),
        ):
            response = authenticated_client.post(
                "/budgets/propose",
                data=self._VALID_FORM,
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "/budgets/" in response.headers.get("Location", "")

    def test_valid_apply_flashes_success_message(self, authenticated_client):
        # Behavior: flash message includes count of budgets applied
        with (
            patch(_PROPOSE_BUDGETS, return_value=[_PROPOSED_A]),
            patch(_APPLY_PROPOSED, return_value=1),
            patch(_GET_BUDGET_PROGRESS, return_value=[]),
            patch(_GET_BUDGETS, return_value=[]),
            patch(_GET_USER_SETTINGS, side_effect=_stub_user_settings),
            patch(_LIST_CATEGORIES, return_value=[]),
        ):
            response = authenticated_client.post(
                "/budgets/propose",
                data=self._VALID_FORM,
                follow_redirects=True,
            )
        assert b"budget" in response.data.lower()


# ===========================================================================
# Section 4 — DB-gated service tests (skipped without DATABASE_URL)
# ===========================================================================

import sqlalchemy as sa


@pytest.fixture(scope="module")
def app_ctx():
    """Module-scoped Flask app context so service calls have current_app."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield


def _uid() -> str:
    """Insert a row into auth.users and return its UUID string."""
    user_id = str(uuid.uuid4())
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO auth.users (id) VALUES (:uid)"),
            {"uid": user_id},
        )
    return user_id


def _insert_category(user_id: str, name: str = "Test Category") -> str:
    """Insert a category row for the given user, return its UUID string."""
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        category_id = conn.execute(
            sa.text(
                "INSERT INTO public.categories (user_id, name)"
                " VALUES (:uid, :name) RETURNING id"
            ),
            {"uid": user_id, "name": name},
        ).scalar()
    return str(category_id)


def _insert_budget(
    user_id: str,
    category_id: str,
    amount: str = "200.00",
) -> str:
    """Insert a budget row directly, return its UUID string."""
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        budget_id = conn.execute(
            sa.text(
                "INSERT INTO public.budgets"
                " (user_id, category_id, amount)"
                " VALUES (:uid, :cid, :amount)"
                " RETURNING id"
            ),
            {
                "uid": user_id,
                "cid": category_id,
                "amount": amount,
            },
        ).scalar()
    return str(budget_id)


def _budget_row_exists(budget_id: str) -> bool:
    engine = sa.create_engine(DATABASE_URL)
    with engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM public.budgets WHERE id = :bid"),
            {"bid": budget_id},
        ).scalar()
    return count > 0


@requires_db
class TestGetBudgetsDB:
    """get_budgets — DB-backed scoping and return type (ADR-0025)."""

    def test_returns_empty_for_new_user(self, app_ctx):
        # Behavior: no budgets exist yet → []
        user_id = _uid()
        result = get_budgets(user_id)
        assert result == []

    def test_returns_budget_for_user(self, app_ctx):
        # Behavior: inserted row is returned as a Budget dataclass
        user_id = _uid()
        category_id = _insert_category(user_id, "Groceries")
        budget_id = _insert_budget(user_id, category_id, amount="300.00")

        result = get_budgets(user_id)

        assert len(result) == 1
        b = result[0]
        assert str(b.id) == budget_id
        assert b.amount == Decimal("300.00")
        assert b.category_name == "Groceries"
        assert isinstance(b, Budget)


@requires_db
class TestUpsertBudgetDB:
    """upsert_budget — create and update paths (ADR-0025)."""

    def test_creates_budget_row_and_returns_budget(self, app_ctx):
        # Behavior: first call creates a row and returns a Budget
        user_id = _uid()
        category_id = _insert_category(user_id, "Transport")

        result = upsert_budget(
            user_id,
            uuid.UUID(category_id),
            Decimal("150.00"),
        )

        assert isinstance(result, Budget)
        assert result.amount == Decimal("150.00")
        assert result.category_name == "Transport"

    def test_second_call_updates_amount(self, app_ctx):
        # Behavior: calling upsert twice for the same category updates amount
        user_id = _uid()
        category_id = _insert_category(user_id, "Dining")

        upsert_budget(user_id, uuid.UUID(category_id), Decimal("200.00"))
        result = upsert_budget(user_id, uuid.UUID(category_id), Decimal("350.00"))

        assert result.amount == Decimal("350.00")
        # Only one row should exist (upsert, not duplicate insert)
        rows = get_budgets(user_id)
        assert len(rows) == 1


@requires_db
class TestDeleteBudgetDB:
    """delete_budget — removal and ownership enforcement (ADR-0025)."""

    def test_removes_budget_row(self, app_ctx):
        # Behavior: delete removes the row from the database
        user_id = _uid()
        category_id = _insert_category(user_id)
        budget_id = _insert_budget(user_id, category_id, amount="200.00")

        assert _budget_row_exists(budget_id)
        delete_budget(user_id, uuid.UUID(budget_id))
        assert not _budget_row_exists(budget_id)

    def test_wrong_user_id_raises_value_error(self, app_ctx):
        # Behavior: cross-user delete attempt → ValueError (user isolation)
        user_a = _uid()
        user_b = _uid()
        category_id = _insert_category(user_a)
        budget_id = _insert_budget(user_a, category_id)

        with pytest.raises(ValueError):
            delete_budget(user_b, uuid.UUID(budget_id))

    def test_row_survives_wrong_user_delete(self, app_ctx):
        # Behavior: failed cross-user delete must not remove the row
        user_a = _uid()
        user_b = _uid()
        category_id = _insert_category(user_a)
        budget_id = _insert_budget(user_a, category_id)

        with pytest.raises(ValueError):
            delete_budget(user_b, uuid.UUID(budget_id))

        assert _budget_row_exists(budget_id), "Row must survive a cross-user delete attempt"


@requires_db
class TestGetBudgetProgressDB:
    """get_budget_progress — no budgets and no spend returns [] (ADR-0025)."""

    def test_no_budgets_no_spend_returns_empty(self, app_ctx):
        # Behavior: fresh user with no data → []
        user_id = _uid()
        result = get_budget_progress(user_id, 2026, 5)
        assert result == []


@requires_db
class TestApplyProposedBudgetsDB:
    """apply_proposed_budgets with replace_existing=False skips existing rows (ADR-0025)."""

    def test_skips_existing_budget_when_replace_existing_false(self, app_ctx):
        # Behavior: if a standing budget already exists for the category,
        # and replace_existing=False, it is skipped and written count does not include it
        user_id = _uid()
        category_id = _insert_category(user_id, "Existing Category")
        _insert_budget(user_id, category_id, amount="100.00")

        proposal = ProposedBudget(
            category_id=uuid.UUID(category_id),
            category_name="Existing Category",
            proposed_amount=Decimal("999.00"),
            months_of_data=3,
            average_monthly_spend=Decimal("999.00"),
        )

        written = apply_proposed_budgets(
            user_id,
            [proposal],
            replace_existing=False,
        )

        assert written == 0

        # The original amount must still be 100.00, not overwritten by 999.00
        budgets = get_budgets(user_id)
        assert len(budgets) == 1
        assert budgets[0].amount == Decimal("100.00")
