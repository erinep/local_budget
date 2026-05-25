"""Route tests for the Intelligence Layer dashboard (ADR-0039).

Tests:
  GET /intelligence/dashboard  — auth gate, 200 path, template content.
  GET /intelligence/report     — 301 permanent redirect to /intelligence/dashboard.
  GET /intelligence/widgets/monthly_totals — HTMX fragment, auth gate, 200 path.
  GET /intelligence/widgets/category_trends — HTMX fragment, auth gate, 200 path.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

import datetime

from app.intelligence.widgets.category_trends import CategoryTrendsVM
from app.intelligence.widgets.category_totals import CategoryTotalItem, CategoryTotalsVM
from app.intelligence.widgets.category_profile import CategoryProfileRow, CategoryProfileVM
from app.intelligence.widgets.top_transactions import TopTransactionItem, TopTransactionsVM
from app.intelligence.widgets.outlier_transactions import OutlierTransactionItem, OutlierTransactionsVM
from app.intelligence.widgets.budget_trend import BudgetTrendCell, BudgetTrendRow, BudgetTrendVM
from app.intelligence.widgets.spend_calendar import SpendCalendarDay, SpendCalendarVM
from app.intelligence.widgets.category_radar import CategoryRadarVM
from app.intelligence.widgets.day_of_week_spend import DayOfWeekSpendVM
from app.intelligence.widgets.subscription_detector import SubscriptionItem, SubscriptionDetectorVM
from app.intelligence.widgets.budget_progress_mtd import BudgetProgressMTDItem, BudgetProgressMTDVM
from app.intelligence.widgets.category_momentum import CategoryMomentumItem, CategoryMomentumVM
from app.intelligence.widgets.spend_forecast import SpendForecastVM
from app.intelligence.widgets.no_spend_days import NoSpendDaysVM
from app.intelligence.widgets.transaction_histogram import TransactionHistogramVM
from app.intelligence.widgets.biggest_spending_days import BigSpendDayItem, BigSpendingDaysVM
from app.intelligence.widgets.category_seasonality import SeasonalityCell, SeasonalityRow, CategorySeasonalityVM
from app.intelligence.widgets.merchant_frequency import MerchantFrequencyItem, MerchantFrequencyVM
from app.intelligence.widgets.small_purchase_drain import SmallPurchaseDrainVM
from app.intelligence.widgets.income_vs_outflow import IncomeVsOutflowVM
from app.intelligence.widgets.spend_by_account import AccountSpendItem, SpendByAccountVM
from app.intelligence.widgets.category_rank_changes import RankChangeItem, CategoryRankChangesVM
from app.intelligence.widgets.budget_win_rate import BudgetWinRateItem, BudgetWinRateVM
from app.intelligence.widgets.financial_health_score import HealthComponent, FinancialHealthScoreVM
from app.intelligence.widgets.rolling_average_spend import RollingAverageSpendVM
from app.intelligence.widgets.cumulative_ytd import CumulativeYTDVM
from app.intelligence.widgets.spending_concentration import SpendingConcentrationVM
from app.intelligence.widgets.new_merchant_detector import NewMerchantItem, NewMerchantDetectorVM
from app.intelligence.widgets.daily_spend_average import DailySpendAverageVM
from app.intelligence.widgets.weekend_splurge import WeekendSplurgeVM
from app.intelligence.widgets.payday_pattern import PaydayPatternVM

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_USER_ID = "00000000-0000-0000-0000-000000000001"

_FAKE_CT_VM = CategoryTrendsVM(
    title="Spending by Category",
    labels=["Apr 2026", "May 2026"],
    datasets=[
        {"label": "Groceries", "data": [400.0, 350.0]},
        {"label": "Dining", "data": [120.0, 95.0]},
    ],
    period_months=12,
)

_PATCH_BUILD_CT   = "app.intelligence.widgets.category_trends.build_category_trends"
_PATCH_BUILD_CTOT = "app.intelligence.widgets.category_totals.build_category_totals"
_PATCH_BUILD_CP   = "app.intelligence.widgets.category_profile.build_category_profile"
_PATCH_BUILD_TT   = "app.intelligence.widgets.top_transactions.build_top_transactions"
_PATCH_BUILD_OT   = "app.intelligence.widgets.outlier_transactions.build_outlier_transactions"
_PATCH_BUILD_BT   = "app.intelligence.widgets.budget_trend.build_budget_trend"
_PATCH_BUILD_SC   = "app.intelligence.widgets.spend_calendar.build_spend_calendar"
_PATCH_BUILD_CR   = "app.intelligence.widgets.category_radar.build_category_radar"
_PATCH_BUILD_DOW  = "app.intelligence.widgets.day_of_week_spend.build_day_of_week_spend"
_PATCH_BUILD_SD   = "app.intelligence.widgets.subscription_detector.build_subscription_detector"
_PATCH_BUILD_BPM  = "app.intelligence.widgets.budget_progress_mtd.build_budget_progress_mtd"
_PATCH_BUILD_CM   = "app.intelligence.widgets.category_momentum.build_category_momentum"
_PATCH_BUILD_SF   = "app.intelligence.widgets.spend_forecast.build_spend_forecast"
_PATCH_BUILD_NSD  = "app.intelligence.widgets.no_spend_days.build_no_spend_days"
_PATCH_BUILD_TH   = "app.intelligence.widgets.transaction_histogram.build_transaction_histogram"
_PATCH_BUILD_BSD  = "app.intelligence.widgets.biggest_spending_days.build_biggest_spending_days"
_PATCH_BUILD_CS   = "app.intelligence.widgets.category_seasonality.build_category_seasonality"
_PATCH_BUILD_MF   = "app.intelligence.widgets.merchant_frequency.build_merchant_frequency"
_PATCH_BUILD_SPD  = "app.intelligence.widgets.small_purchase_drain.build_small_purchase_drain"
_PATCH_BUILD_IVO  = "app.intelligence.widgets.income_vs_outflow.build_income_vs_outflow"
_PATCH_BUILD_SBA  = "app.intelligence.widgets.spend_by_account.build_spend_by_account"
_PATCH_BUILD_CRC  = "app.intelligence.widgets.category_rank_changes.build_category_rank_changes"
_PATCH_BUILD_BWR  = "app.intelligence.widgets.budget_win_rate.build_budget_win_rate"
_PATCH_BUILD_FHS  = "app.intelligence.widgets.financial_health_score.build_financial_health_score"
_PATCH_BUILD_RAS  = "app.intelligence.widgets.rolling_average_spend.build_rolling_average_spend"
_PATCH_BUILD_YTD  = "app.intelligence.widgets.cumulative_ytd.build_cumulative_ytd"
_PATCH_BUILD_SCON = "app.intelligence.widgets.spending_concentration.build_spending_concentration"
_PATCH_BUILD_NMD  = "app.intelligence.widgets.new_merchant_detector.build_new_merchant_detector"
_PATCH_BUILD_DSA  = "app.intelligence.widgets.daily_spend_average.build_daily_spend_average"
_PATCH_BUILD_WS   = "app.intelligence.widgets.weekend_splurge.build_weekend_splurge"
_PATCH_BUILD_PP   = "app.intelligence.widgets.payday_pattern.build_payday_pattern"

_FAKE_CTOT_VM = CategoryTotalsVM(
    title="Category Totals",
    items=[
        CategoryTotalItem(label="Groceries", spend=400.0, is_uncategorized=False),
        CategoryTotalItem(label="Uncategorized", spend=50.0, is_uncategorized=True),
    ],
    period_months=12,
    category_amounts={
        "Groceries": {"labels": ["Superstore", "Metro", "Loblaws"], "values": [120.0, 80.0, 60.0]},
        "Uncategorized": {"labels": ["Unknown"], "values": [50.0]},
    },
)

_FAKE_CP_VM = CategoryProfileVM(
    title="Category Profile",
    rows=[
        CategoryProfileRow(label="Groceries", count=12, total=400.0, mean=33.33,
                           std_dev=5.0, cv=0.15, consistency="Consistent", is_uncategorized=False),
        CategoryProfileRow(label="Transportation", count=8, total=320.0, mean=40.0,
                           std_dev=55.0, cv=1.38, consistency="Irregular", is_uncategorized=False),
    ],
    period_months=12,
    total_txns=100,
    categorized_count=87,
    uncategorized_count=13,
    pct_categorized=87.0,
    consistent_count=1,
    mixed_count=0,
    irregular_count=1,
    total_spend=720.0,
    categorized_spend=400.0,
    uncategorized_spend=320.0,
    pct_spend_categorized=55.6,
)

_FAKE_TT_VM = TopTransactionsVM(
    title="Top Transactions",
    items=[
        TopTransactionItem(rank=1, description="Big Purchase", category_name="Groceries",
                           amount=450.0, date=datetime.date(2026, 4, 1)),
    ],
    period_months=12,
    limit=20,
)

_FAKE_OT_VM = OutlierTransactionsVM(
    title="Unusual Transactions",
    items=[
        OutlierTransactionItem(description="Huge Bill", category_name="Utilities",
                               amount=320.0, date=datetime.date(2026, 4, 5),
                               category_mean=80.0, z_score=2.4),
    ],
    period_months=12,
    threshold_sigma=2.0,
)

_FAKE_BT_VM = BudgetTrendVM(
    title="Budget Trend",
    month_labels=["Apr 2026", "May 2026"],
    rows=[
        BudgetTrendRow(
            category_name="Groceries",
            cells=[
                BudgetTrendCell(status="under", pct_used=72.0, actual=288.0),
                BudgetTrendCell(status="over",  pct_used=112.0, actual=448.0),
            ],
        ),
    ],
    period_months=12,
)

_FAKE_SC_VM = SpendCalendarVM(
    title="Spend Calendar",
    weeks=[
        [SpendCalendarDay(date_str="Jan 1", amount=0.0, level=0)] * 7,
    ],
    month_markers=[[0, "Jan"]],
    period_days=365,
    max_day_spend=0.0,
)

_FAKE_CR_VM = CategoryRadarVM(
    title="Category Radar",
    labels=["Groceries", "Dining"],
    current_month=[200.0, 80.0],
    historical_avg=[350.0, 100.0],
    current_month_label="May 2026",
    period_months=12,
)

_FAKE_DOW_VM = DayOfWeekSpendVM(
    title="Day of Week Spend",
    labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    totals=[100.0, 80.0, 60.0, 90.0, 120.0, 200.0, 150.0],
    counts=[4, 4, 4, 4, 4, 4, 4],
    averages=[25.0, 20.0, 15.0, 22.5, 30.0, 50.0, 37.5],
    period_months=12,
)

_FAKE_SD_VM = SubscriptionDetectorVM(
    title="Subscription Detector",
    items=[
        SubscriptionItem(
            description="Streaming Service",
            category_name="Entertainment",
            typical_amount=14.99,
            months_seen=6,
            total_paid=89.94,
        ),
    ],
    period_months=12,
    monthly_total=14.99,
)

_FAKE_BPM_VM = BudgetProgressMTDVM(
    title="Budget Progress",
    items=[
        BudgetProgressMTDItem(
            category_name="Groceries",
            target=500.0,
            actual=200.0,
            projected=320.0,
            pct_actual=40.0,
            pct_projected=64.0,
            status="under",
        ),
    ],
    current_month_label="May 2026",
    days_elapsed=15,
    days_in_month=31,
    pct_of_month=48.4,
)

_FAKE_CM_VM = CategoryMomentumVM(
    title="Category Momentum",
    items=[
        CategoryMomentumItem(category_name="Groceries", recent_avg=300.0, prior_avg=250.0, change_pct=20.0, direction="up"),
        CategoryMomentumItem(category_name="Dining", recent_avg=80.0, prior_avg=100.0, change_pct=-20.0, direction="down"),
    ],
    period_label="last 3 vs prior 3 months",
)

_FAKE_SF_VM = SpendForecastVM(
    title="Spend Forecast",
    labels=["1", "2", "3"],
    actuals=[100.0, 200.0, None],
    forecast=[None, None, 300.0],
    today_day=2,
    days_in_month=31,
    actual_to_date=200.0,
    projected_total=3100.0,
    last_month_total=2800.0,
)

_FAKE_NSD_VM = NoSpendDaysVM(
    title="No-Spend Days",
    labels=["Apr 2026", "May 2026"],
    counts=[12, 10],
    period_months=6,
    best_month="Apr 2026",
    best_count=12,
)

_FAKE_TH_VM = TransactionHistogramVM(
    title="Transaction Size Distribution",
    labels=["$0-10", "$10-25", "$25-50", "$50-100", "$100-250", "$250+"],
    counts=[5, 10, 8, 4, 2, 1],
    totals=[30.0, 180.0, 300.0, 320.0, 400.0, 280.0],
    period_months=6,
)

_FAKE_BSD_VM = BigSpendingDaysVM(
    title="Biggest Spending Days",
    items=[
        BigSpendDayItem(date_str="Apr 15", total=450.0, transaction_count=3, top_category="Groceries"),
        BigSpendDayItem(date_str="May 1", total=320.0, transaction_count=2, top_category="Utilities"),
    ],
    period_months=6,
)

_FAKE_CS_VM = CategorySeasonalityVM(
    title="Category Seasonality",
    month_labels=["Apr 2026", "May 2026"],
    rows=[
        SeasonalityRow(
            category_name="Groceries",
            cells=[
                SeasonalityCell(raw=300.0, delta_pct=-10.0, level=-1),
                SeasonalityCell(raw=400.0, delta_pct=10.0, level=0),
            ],
        ),
    ],
    period_months=6,
)

_FAKE_MF_VM = MerchantFrequencyVM(
    title="Merchant Frequency",
    items=[
        MerchantFrequencyItem(description="Generic Store", visit_count=10, total_spend=500.0, category_name="Groceries", avg_amount=50.0),
        MerchantFrequencyItem(description="Coffee Shop", visit_count=8, total_spend=80.0, category_name="Dining", avg_amount=10.0),
    ],
    period_months=6,
)

_FAKE_SPD_VM = SmallPurchaseDrainVM(
    title="Small Purchase Drain",
    threshold=25.0,
    total_count=30,
    total_spend=450.0,
    monthly_labels=["Apr 2026", "May 2026"],
    monthly_counts=[15, 15],
    monthly_totals=[225.0, 225.0],
    period_months=6,
    avg_per_month=75.0,
)

_FAKE_IVO_VM = IncomeVsOutflowVM(
    title="Income vs Outflow",
    labels=["Apr 2026", "May 2026"],
    income=[3000.0, 3200.0],
    outflow=[2500.0, 2800.0],
    net=[500.0, 400.0],
    period_months=6,
    has_income=True,
)

_FAKE_SBA_VM = SpendByAccountVM(
    title="Spend by Account",
    items=[
        AccountSpendItem(account_name="Chequing", total_spend=2000.0, transaction_count=20, pct_of_total=66.7),
        AccountSpendItem(account_name="Credit Card", total_spend=1000.0, transaction_count=10, pct_of_total=33.3),
    ],
    total_spend=3000.0,
    period_months=6,
    has_multiple_accounts=True,
)

_FAKE_CRC_VM = CategoryRankChangesVM(
    title="Category Rank Changes",
    items=[
        RankChangeItem(category_name="Groceries", current_rank=1, prior_rank=2, rank_change=1, current_spend=1200.0, prior_spend=900.0),
        RankChangeItem(category_name="Dining", current_rank=2, prior_rank=1, rank_change=-1, current_spend=900.0, prior_spend=1100.0),
    ],
    current_label="last 3 months",
    prior_label="prior 3 months",
)

_FAKE_BWR_VM = BudgetWinRateVM(
    title="Budget Win Rate",
    items=[
        BudgetWinRateItem(category_name="Groceries", under_count=4, total_months=6, win_rate=66.7, current_streak=2),
        BudgetWinRateItem(category_name="Dining", under_count=3, total_months=6, win_rate=50.0, current_streak=0),
    ],
    period_months=6,
)

_FAKE_FHS_VM = FinancialHealthScoreVM(
    title="Financial Health Score",
    total_score=72.5,
    grade="C",
    components=[
        HealthComponent(name="Categorization", score=16.0, max_score=20.0, label="80% categorized"),
        HealthComponent(name="Budget Adherence", score=14.0, max_score=20.0, label="70% under budget"),
        HealthComponent(name="Transaction Regularity", score=18.0, max_score=20.0, label="Few outliers"),
        HealthComponent(name="Subscription Load", score=16.0, max_score=20.0, label="20% subscriptions"),
        HealthComponent(name="Spending Trend", score=8.5, max_score=20.0, label="Spending up 15%"),
    ],
    period_months=6,
)

_FAKE_RAS_VM = RollingAverageSpendVM(
    title="Rolling Average Spend",
    labels=["Mar 2026", "Apr 2026", "May 2026"],
    monthly_totals=[1200.0, 1400.0, 1100.0],
    rolling_3m=[None, None, 1233.33],
    period_months=12,
)

_FAKE_YTD_VM = CumulativeYTDVM(
    title="Cumulative YTD Spend",
    labels=["Jan", "Feb", "Mar", "Apr", "May"],
    current_year=[1200.0, 2500.0, 3800.0, 5300.0, 6500.0],
    prior_year=[None, None, None, None, None],
    current_year_label="2026",
    prior_year_label="2025",
    has_prior_year=False,
)

_FAKE_SCON_VM = SpendingConcentrationVM(
    title="Spending Concentration",
    labels=["Apr 2026", "May 2026"],
    top1_pct=[45.0, 50.0],
    top3_pct=[75.0, 80.0],
    top5_pct=[90.0, 92.0],
    period_months=6,
)

_FAKE_NMD_VM = NewMerchantDetectorVM(
    title="New Merchant Detector",
    items=[
        NewMerchantItem(description="New Place", category_name="Dining", first_seen_str="May 10", amount=25.0, total_spend=25.0),
    ],
    period_months=6,
    new_count=1,
)

_FAKE_DSA_VM = DailySpendAverageVM(
    title="Daily Spend Average",
    this_month_daily_avg=45.0,
    last_month_daily_avg=42.0,
    period_avg=40.0,
    this_month_label="May 2026",
    days_elapsed=15,
    sparkline_labels=["Apr 2026", "May 2026"],
    sparkline_values=[42.0, 45.0],
    period_months=12,
)

_FAKE_WS_VM = WeekendSplurgeVM(
    title="Weekend Splurge",
    labels=["Apr 2026", "May 2026"],
    weekday_totals=[1800.0, 1600.0],
    weekend_totals=[700.0, 900.0],
    weekend_pcts=[28.0, 36.0],
    period_months=6,
    avg_weekend_pct=32.0,
)

_FAKE_PP_VM = PaydayPatternVM(
    title="Payday Pattern",
    labels=[str(d) for d in range(1, 32)],
    values=[50.0] * 31,
    counts=[6] * 31,
    period_months=6,
)

_ALL_WIDGET_PATCHES = [
    (_PATCH_BUILD_CT,   _FAKE_CT_VM),
    (_PATCH_BUILD_CTOT, _FAKE_CTOT_VM),
    (_PATCH_BUILD_CP,   _FAKE_CP_VM),
    (_PATCH_BUILD_TT,   _FAKE_TT_VM),
    (_PATCH_BUILD_OT,   _FAKE_OT_VM),
    (_PATCH_BUILD_BT,   _FAKE_BT_VM),
    (_PATCH_BUILD_SC,   _FAKE_SC_VM),
    (_PATCH_BUILD_CR,   _FAKE_CR_VM),
    (_PATCH_BUILD_DOW,  _FAKE_DOW_VM),
    (_PATCH_BUILD_SD,   _FAKE_SD_VM),
    (_PATCH_BUILD_BPM,  _FAKE_BPM_VM),
    (_PATCH_BUILD_CM,   _FAKE_CM_VM),
    (_PATCH_BUILD_SF,   _FAKE_SF_VM),
    (_PATCH_BUILD_NSD,  _FAKE_NSD_VM),
    (_PATCH_BUILD_TH,   _FAKE_TH_VM),
    (_PATCH_BUILD_BSD,  _FAKE_BSD_VM),
    (_PATCH_BUILD_CS,   _FAKE_CS_VM),
    (_PATCH_BUILD_MF,   _FAKE_MF_VM),
    (_PATCH_BUILD_SPD,  _FAKE_SPD_VM),
    (_PATCH_BUILD_IVO,  _FAKE_IVO_VM),
    (_PATCH_BUILD_SBA,  _FAKE_SBA_VM),
    (_PATCH_BUILD_CRC,  _FAKE_CRC_VM),
    (_PATCH_BUILD_BWR,  _FAKE_BWR_VM),
    (_PATCH_BUILD_FHS,  _FAKE_FHS_VM),
    (_PATCH_BUILD_RAS,  _FAKE_RAS_VM),
    (_PATCH_BUILD_YTD,  _FAKE_YTD_VM),
    (_PATCH_BUILD_SCON, _FAKE_SCON_VM),
    (_PATCH_BUILD_NMD,  _FAKE_NMD_VM),
    (_PATCH_BUILD_DSA,  _FAKE_DSA_VM),
    (_PATCH_BUILD_WS,   _FAKE_WS_VM),
    (_PATCH_BUILD_PP,   _FAKE_PP_VM),
]


def _patch_all_widgets():
    from contextlib import ExitStack
    stack = ExitStack()
    for path, val in _ALL_WIDGET_PATCHES:
        stack.enter_context(patch(path, return_value=val))
    return stack


# ===========================================================================
# GET /intelligence/dashboard
# ===========================================================================

class TestDashboardRoute:
    """GET /intelligence/dashboard — auth gate and 200 path."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/dashboard", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with _patch_all_widgets():
            response = authenticated_client.get("/intelligence/dashboard")
        assert response.status_code == 200

    def test_response_contains_dashboard_content(self, authenticated_client):
        with _patch_all_widgets():
            response = authenticated_client.get("/intelligence/dashboard")
        assert response.status_code == 200
        body = response.data.lower()
        assert b"dashboard" in body or b"spending" in body

    def test_route_registered(self, client):
        response = client.get("/intelligence/dashboard", follow_redirects=False)
        assert response.status_code != 404


# ===========================================================================
# GET /intelligence/report  (301 redirect)
# ===========================================================================

class TestReportRedirect:
    """GET /intelligence/report must return 301 → /intelligence/dashboard."""

    def test_returns_301(self, client):
        response = client.get("/intelligence/report", follow_redirects=False)
        assert response.status_code == 301

    def test_location_points_to_dashboard(self, client):
        response = client.get("/intelligence/report", follow_redirects=False)
        assert "/intelligence/dashboard" in response.headers.get("Location", "")

    def test_follows_to_dashboard(self, client):
        # Unauthenticated follow lands at login, but the redirect chain starts at /intelligence/dashboard.
        response = client.get("/intelligence/report", follow_redirects=True)
        assert b"login" in response.data.lower() or b"dashboard" in response.data.lower()


# ===========================================================================
# GET /intelligence/widgets/category_trends
# ===========================================================================

class TestCategoryTrendsWidget:
    """HTMX fragment endpoint for category_trends widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_trends", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CT, return_value=_FAKE_CT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_trends")
        assert response.status_code == 200

    def test_response_contains_chart_data(self, authenticated_client):
        with patch(_PATCH_BUILD_CT, return_value=_FAKE_CT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_trends")
        assert b"chart-category-trends" in response.data

    def test_unknown_key_returns_404(self, authenticated_client):
        response = authenticated_client.get("/intelligence/widgets/nonexistent")
        assert response.status_code == 404


# ===========================================================================
# GET /intelligence/widgets/category_totals
# ===========================================================================

class TestCategoryTotalsWidget:
    """HTMX fragment endpoint for category_totals widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_totals", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CTOT, return_value=_FAKE_CTOT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_totals")
        assert response.status_code == 200

    def test_response_contains_chart_canvas(self, authenticated_client):
        with patch(_PATCH_BUILD_CTOT, return_value=_FAKE_CTOT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_totals")
        assert b"chart-category-totals" in response.data


# ===========================================================================
# GET /intelligence/widgets/category_profile
# ===========================================================================

class TestCategoryProfileWidget:
    """HTMX fragment endpoint for category_profile widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_profile", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CP, return_value=_FAKE_CP_VM):
            response = authenticated_client.get("/intelligence/widgets/category_profile")
        assert response.status_code == 200

    def test_consistency_badges_in_response(self, authenticated_client):
        with patch(_PATCH_BUILD_CP, return_value=_FAKE_CP_VM):
            response = authenticated_client.get("/intelligence/widgets/category_profile")
        assert b"Consistent" in response.data
        assert b"Irregular" in response.data

    def test_health_summary_in_response(self, authenticated_client):
        with patch(_PATCH_BUILD_CP, return_value=_FAKE_CP_VM):
            response = authenticated_client.get("/intelligence/widgets/category_profile")
        assert b"87.0" in response.data
        assert b"chart-categorization-health" in response.data
