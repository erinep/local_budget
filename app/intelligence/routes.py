"""Intelligence Layer routes — dashboard.

Blueprint: intelligence_bp, url_prefix="/intelligence" (ADR-0004, ADR-0024).

Route table:
  GET /intelligence/dashboard          dashboard  Widget dashboard (Phase 5d, ADR-0039).
  GET /intelligence/widgets/<key>      widget     HTMX fragment endpoint for a single widget.
  GET /intelligence/report             →301       Permanent redirect to /intelligence/dashboard.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for, g

from app.intelligence.widgets import REGISTRY
import app.intelligence.widgets.category_trends         # noqa: F401
import app.intelligence.widgets.category_trends_stacked # noqa: F401
import app.intelligence.widgets.category_totals         # noqa: F401
import app.intelligence.widgets.category_profile        # noqa: F401
import app.intelligence.widgets.top_transactions        # noqa: F401
import app.intelligence.widgets.outlier_transactions    # noqa: F401
import app.intelligence.widgets.budget_trend            # noqa: F401
import app.intelligence.widgets.spend_calendar          # noqa: F401
import app.intelligence.widgets.category_radar          # noqa: F401
import app.intelligence.widgets.day_of_week_spend       # noqa: F401
import app.intelligence.widgets.subscription_detector   # noqa: F401
import app.intelligence.widgets.budget_progress_mtd     # noqa: F401
import app.intelligence.widgets.category_momentum      # noqa: F401
import app.intelligence.widgets.spend_forecast         # noqa: F401
import app.intelligence.widgets.no_spend_days          # noqa: F401
import app.intelligence.widgets.transaction_histogram  # noqa: F401
import app.intelligence.widgets.biggest_spending_days  # noqa: F401
import app.intelligence.widgets.category_seasonality   # noqa: F401
import app.intelligence.widgets.merchant_frequency     # noqa: F401
import app.intelligence.widgets.small_purchase_drain   # noqa: F401
import app.intelligence.widgets.income_vs_outflow      # noqa: F401
import app.intelligence.widgets.spend_by_account       # noqa: F401
import app.intelligence.widgets.category_rank_changes  # noqa: F401
import app.intelligence.widgets.budget_win_rate        # noqa: F401
import app.intelligence.widgets.financial_health_score # noqa: F401
import app.intelligence.widgets.rolling_average_spend  # noqa: F401
import app.intelligence.widgets.cumulative_ytd         # noqa: F401
import app.intelligence.widgets.spending_concentration # noqa: F401
import app.intelligence.widgets.new_merchant_detector  # noqa: F401
import app.intelligence.widgets.daily_spend_average    # noqa: F401
import app.intelligence.widgets.weekend_splurge        # noqa: F401
import app.intelligence.widgets.payday_pattern         # noqa: F401
from app.middleware.auth import login_required

intelligence_bp = Blueprint("intelligence", __name__, url_prefix="/intelligence")

_ACCENT   = '#0f766e'
_ERROR    = '#dc2626'
_MUTED    = '#94a3b8'
_PALETTE  = ['#0f766e','#2563eb','#d97706','#7c3aed','#db2777','#059669','#ea580c','#0891b2']


def _category_trends_vm(user_id, period_months):
    from app.intelligence.widgets.category_trends import build_category_trends
    ct_vm = build_category_trends(user_id, period_months)
    n = len(ct_vm.labels)
    total = [sum(ds["data"][i] for ds in ct_vm.datasets) for i in range(n)]
    chart = {
        "labels": ct_vm.labels,
        "total": total,
        "datasets": ct_vm.datasets,
    }
    return ct_vm, chart


def _category_profile_vm(user_id, period_months):
    from app.intelligence.widgets.category_profile import build_category_profile
    vm = build_category_profile(user_id, period_months)
    return vm


def _top_transactions_vm(user_id, period_months):
    from app.intelligence.widgets.top_transactions import build_top_transactions
    return build_top_transactions(user_id, period_months)


def _outlier_transactions_vm(user_id, period_months):
    from app.intelligence.widgets.outlier_transactions import build_outlier_transactions
    return build_outlier_transactions(user_id, period_months)


def _budget_trend_vm(user_id, period_months):
    from app.intelligence.widgets.budget_trend import build_budget_trend
    return build_budget_trend(user_id, min(period_months, 12))


def _spend_calendar_vm(user_id):
    from app.intelligence.widgets.spend_calendar import build_spend_calendar
    return build_spend_calendar(user_id)


def _category_radar_vm(user_id, period_months):
    from app.intelligence.widgets.category_radar import build_category_radar
    vm = build_category_radar(user_id, period_months)
    chart = {
        "labels": vm.labels,
        "current": vm.current_month,
        "avg": vm.historical_avg,
        "current_label": vm.current_month_label,
    }
    return vm, chart


def _day_of_week_vm(user_id, period_months):
    from app.intelligence.widgets.day_of_week_spend import build_day_of_week_spend
    vm = build_day_of_week_spend(user_id, period_months)
    chart = {"labels": vm.labels, "values": vm.averages}
    return vm, chart


def _subscription_detector_vm(user_id, period_months):
    from app.intelligence.widgets.subscription_detector import build_subscription_detector
    return build_subscription_detector(user_id, period_months)


def _budget_progress_mtd_vm(user_id):
    from app.intelligence.widgets.budget_progress_mtd import build_budget_progress_mtd
    return build_budget_progress_mtd(user_id)


def _category_momentum_vm(user_id, period_months):
    from app.intelligence.widgets.category_momentum import build_category_momentum
    return build_category_momentum(user_id, period_months)


def _spend_forecast_vm(user_id):
    from app.intelligence.widgets.spend_forecast import build_spend_forecast
    vm = build_spend_forecast(user_id)
    chart = {"labels": vm.labels, "actuals": vm.actuals, "forecast": vm.forecast}
    return vm, chart


def _no_spend_days_vm(user_id, period_months):
    from app.intelligence.widgets.no_spend_days import build_no_spend_days
    vm = build_no_spend_days(user_id, period_months)
    chart = {"labels": vm.labels, "values": vm.counts}
    return vm, chart


def _transaction_histogram_vm(user_id, period_months):
    from app.intelligence.widgets.transaction_histogram import build_transaction_histogram
    vm = build_transaction_histogram(user_id, period_months)
    chart = {"labels": vm.labels, "counts": vm.counts, "totals": vm.totals}
    return vm, chart


def _biggest_spending_days_vm(user_id, period_months):
    from app.intelligence.widgets.biggest_spending_days import build_biggest_spending_days
    return build_biggest_spending_days(user_id, period_months)


def _category_seasonality_vm(user_id, period_months):
    from app.intelligence.widgets.category_seasonality import build_category_seasonality
    return build_category_seasonality(user_id, period_months)


def _merchant_frequency_vm(user_id, period_months):
    from app.intelligence.widgets.merchant_frequency import build_merchant_frequency
    return build_merchant_frequency(user_id, period_months)


def _small_purchase_drain_vm(user_id, period_months):
    from app.intelligence.widgets.small_purchase_drain import build_small_purchase_drain
    vm = build_small_purchase_drain(user_id, period_months)
    chart = {"labels": vm.monthly_labels, "counts": vm.monthly_counts, "totals": vm.monthly_totals}
    return vm, chart


def _income_vs_outflow_vm(user_id, period_months):
    from app.intelligence.widgets.income_vs_outflow import build_income_vs_outflow
    vm = build_income_vs_outflow(user_id, period_months)
    chart = {"labels": vm.labels, "income": vm.income, "outflow": vm.outflow}
    return vm, chart


def _spend_by_account_vm(user_id, period_months):
    from app.intelligence.widgets.spend_by_account import build_spend_by_account
    vm = build_spend_by_account(user_id, period_months)
    chart = {
        "labels": [item.account_name for item in vm.items],
        "values": [item.total_spend for item in vm.items],
        "pcts": [item.pct_of_total for item in vm.items],
    }
    return vm, chart


def _category_rank_changes_vm(user_id, period_months):
    from app.intelligence.widgets.category_rank_changes import build_category_rank_changes
    return build_category_rank_changes(user_id, period_months)


def _budget_win_rate_vm(user_id, period_months):
    from app.intelligence.widgets.budget_win_rate import build_budget_win_rate
    return build_budget_win_rate(user_id, period_months)


def _financial_health_score_vm(user_id, period_months):
    from app.intelligence.widgets.financial_health_score import build_financial_health_score
    return build_financial_health_score(user_id, period_months)


def _rolling_average_spend_vm(user_id, period_months):
    from app.intelligence.widgets.rolling_average_spend import build_rolling_average_spend
    vm = build_rolling_average_spend(user_id, period_months)
    chart = {"labels": vm.labels, "monthly": vm.monthly_totals, "rolling": vm.rolling_3m}
    return vm, chart


def _cumulative_ytd_vm(user_id):
    from app.intelligence.widgets.cumulative_ytd import build_cumulative_ytd
    vm = build_cumulative_ytd(user_id)
    chart = {
        "labels": vm.labels,
        "current": vm.current_year,
        "prior": vm.prior_year,
        "current_label": vm.current_year_label,
        "prior_label": vm.prior_year_label,
        "has_prior": vm.has_prior_year,
    }
    return vm, chart


def _spending_concentration_vm(user_id, period_months):
    from app.intelligence.widgets.spending_concentration import build_spending_concentration
    vm = build_spending_concentration(user_id, period_months)
    chart = {"labels": vm.labels, "top1": vm.top1_pct, "top3": vm.top3_pct, "top5": vm.top5_pct}
    return vm, chart


def _new_merchant_detector_vm(user_id, period_months):
    from app.intelligence.widgets.new_merchant_detector import build_new_merchant_detector
    return build_new_merchant_detector(user_id, period_months)


def _daily_spend_average_vm(user_id, period_months):
    from app.intelligence.widgets.daily_spend_average import build_daily_spend_average
    vm = build_daily_spend_average(user_id, period_months)
    chart = {"labels": vm.sparkline_labels, "values": vm.sparkline_values}
    return vm, chart


def _weekend_splurge_vm(user_id, period_months):
    from app.intelligence.widgets.weekend_splurge import build_weekend_splurge
    vm = build_weekend_splurge(user_id, period_months)
    chart = {"labels": vm.labels, "weekday": vm.weekday_totals, "weekend": vm.weekend_totals}
    return vm, chart


def _payday_pattern_vm(user_id, period_months):
    from app.intelligence.widgets.payday_pattern import build_payday_pattern
    vm = build_payday_pattern(user_id, period_months)
    chart = {"labels": vm.labels, "values": vm.values, "counts": vm.counts}
    return vm, chart


def _category_totals_vm(user_id, period_months):
    from app.intelligence.widgets.category_totals import build_category_totals
    vm = build_category_totals(user_id, period_months)
    _TOTAL = '#475569'
    colors = [_ERROR if item.is_uncategorized else _TOTAL for item in vm.items]
    chart = {
        "labels": [item.label for item in vm.items],
        "values": [item.spend for item in vm.items],
        "colors": colors,
        "amounts": vm.category_amounts,
    }
    return vm, chart


@intelligence_bp.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    """Widget dashboard (Phase 5d, ADR-0039)."""
    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    ct_vm,   ct_chart   = _category_trends_vm(g.user.id, period_months)
    ctot_vm, ctot_chart = _category_totals_vm(g.user.id, period_months)
    cp_vm               = _category_profile_vm(g.user.id, period_months)
    tt_vm               = _top_transactions_vm(g.user.id, period_months)
    ot_vm               = _outlier_transactions_vm(g.user.id, period_months)
    bt_vm               = _budget_trend_vm(g.user.id, period_months)
    sc_vm               = _spend_calendar_vm(g.user.id)
    cr_vm, cr_chart     = _category_radar_vm(g.user.id, period_months)
    dow_vm, dow_chart   = _day_of_week_vm(g.user.id, period_months)
    sd_vm               = _subscription_detector_vm(g.user.id, period_months)
    bpm_vm              = _budget_progress_mtd_vm(g.user.id)

    cm_vm                           = _category_momentum_vm(g.user.id, period_months)
    sf_vm,   sf_chart               = _spend_forecast_vm(g.user.id)
    nsd_vm,  nsd_chart              = _no_spend_days_vm(g.user.id, period_months)
    th_vm,   th_chart               = _transaction_histogram_vm(g.user.id, period_months)
    bsd_vm                          = _biggest_spending_days_vm(g.user.id, period_months)
    cs_vm                           = _category_seasonality_vm(g.user.id, period_months)
    mf_vm                           = _merchant_frequency_vm(g.user.id, period_months)
    spd_vm,  spd_chart              = _small_purchase_drain_vm(g.user.id, period_months)
    ivo_vm,  ivo_chart              = _income_vs_outflow_vm(g.user.id, period_months)
    sba_vm,  sba_chart              = _spend_by_account_vm(g.user.id, period_months)
    crc_vm                          = _category_rank_changes_vm(g.user.id, period_months)
    bwr_vm                          = _budget_win_rate_vm(g.user.id, period_months)
    fhs_vm                          = _financial_health_score_vm(g.user.id, period_months)
    ras_vm,  ras_chart              = _rolling_average_spend_vm(g.user.id, period_months)
    ytd_vm,  ytd_chart              = _cumulative_ytd_vm(g.user.id)
    scon_vm, scon_chart             = _spending_concentration_vm(g.user.id, period_months)
    nmd_vm                          = _new_merchant_detector_vm(g.user.id, period_months)
    dsa_vm,  dsa_chart              = _daily_spend_average_vm(g.user.id, period_months)
    ws_vm,   ws_chart               = _weekend_splurge_vm(g.user.id, period_months)
    pp_vm,   pp_chart               = _payday_pattern_vm(g.user.id, period_months)

    return render_template(
        "intelligence/dashboard.html",
        category_trends=ct_vm,          category_trends_chart=ct_chart,
        category_totals=ctot_vm,        category_totals_chart=ctot_chart,
        category_profile=cp_vm,
        top_transactions=tt_vm,
        outlier_transactions=ot_vm,
        budget_trend=bt_vm,
        spend_calendar=sc_vm,
        category_radar=cr_vm,           category_radar_chart=cr_chart,
        day_of_week_spend=dow_vm,       day_of_week_chart=dow_chart,
        subscription_detector=sd_vm,
        budget_progress_mtd=bpm_vm,
        category_momentum=cm_vm,
        spend_forecast=sf_vm,           spend_forecast_chart=sf_chart,
        no_spend_days=nsd_vm,           no_spend_days_chart=nsd_chart,
        transaction_histogram=th_vm,    transaction_histogram_chart=th_chart,
        biggest_spending_days=bsd_vm,
        category_seasonality=cs_vm,
        merchant_frequency=mf_vm,
        small_purchase_drain=spd_vm,    small_purchase_drain_chart=spd_chart,
        income_vs_outflow=ivo_vm,       income_vs_outflow_chart=ivo_chart,
        spend_by_account=sba_vm,        spend_by_account_chart=sba_chart,
        category_rank_changes=crc_vm,
        budget_win_rate=bwr_vm,
        financial_health_score=fhs_vm,
        rolling_average_spend=ras_vm,   rolling_average_chart=ras_chart,
        cumulative_ytd=ytd_vm,          cumulative_ytd_chart=ytd_chart,
        spending_concentration=scon_vm, spending_concentration_chart=scon_chart,
        new_merchant_detector=nmd_vm,
        daily_spend_average=dsa_vm,     daily_avg_chart=dsa_chart,
        weekend_splurge=ws_vm,          weekend_splurge_chart=ws_chart,
        payday_pattern=pp_vm,           payday_pattern_chart=pp_chart,
    )


@intelligence_bp.route("/widgets/<key>", endpoint="widget")
@login_required
def widget(key: str):
    """HTMX fragment endpoint — returns a single widget's HTML (ADR-0039 §3)."""
    if key not in REGISTRY:
        abort(404)

    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    if key in ("category_trends", "category_trends_stacked"):
        vm, chart = _category_trends_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_trends=vm, category_trends_chart=chart)

    if key == "category_totals":
        vm, chart = _category_totals_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_totals=vm, category_totals_chart=chart)

    if key == "category_profile":
        vm = _category_profile_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_profile=vm)

    if key == "top_transactions":
        vm = _top_transactions_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, top_transactions=vm)

    if key == "outlier_transactions":
        vm = _outlier_transactions_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, outlier_transactions=vm)

    if key == "budget_trend":
        vm = _budget_trend_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, budget_trend=vm)

    if key == "spend_calendar":
        vm = _spend_calendar_vm(g.user.id)
        return render_template(REGISTRY[key].template, spend_calendar=vm)

    if key == "category_radar":
        vm, chart = _category_radar_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_radar=vm, category_radar_chart=chart)

    if key == "day_of_week_spend":
        vm, chart = _day_of_week_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, day_of_week_spend=vm, day_of_week_chart=chart)

    if key == "subscription_detector":
        vm = _subscription_detector_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, subscription_detector=vm)

    if key == "budget_progress_mtd":
        vm = _budget_progress_mtd_vm(g.user.id)
        return render_template(REGISTRY[key].template, budget_progress_mtd=vm)

    if key == "category_momentum":
        vm = _category_momentum_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_momentum=vm)

    if key == "spend_forecast":
        vm, chart = _spend_forecast_vm(g.user.id)
        return render_template(REGISTRY[key].template, spend_forecast=vm, spend_forecast_chart=chart)

    if key == "no_spend_days":
        vm, chart = _no_spend_days_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, no_spend_days=vm, no_spend_days_chart=chart)

    if key == "transaction_histogram":
        vm, chart = _transaction_histogram_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, transaction_histogram=vm, transaction_histogram_chart=chart)

    if key == "biggest_spending_days":
        vm = _biggest_spending_days_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, biggest_spending_days=vm)

    if key == "category_seasonality":
        vm = _category_seasonality_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_seasonality=vm)

    if key == "merchant_frequency":
        vm = _merchant_frequency_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, merchant_frequency=vm)

    if key == "small_purchase_drain":
        vm, chart = _small_purchase_drain_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, small_purchase_drain=vm, small_purchase_drain_chart=chart)

    if key == "income_vs_outflow":
        vm, chart = _income_vs_outflow_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, income_vs_outflow=vm, income_vs_outflow_chart=chart)

    if key == "spend_by_account":
        vm, chart = _spend_by_account_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, spend_by_account=vm, spend_by_account_chart=chart)

    if key == "category_rank_changes":
        vm = _category_rank_changes_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_rank_changes=vm)

    if key == "budget_win_rate":
        vm = _budget_win_rate_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, budget_win_rate=vm)

    if key == "financial_health_score":
        vm = _financial_health_score_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, financial_health_score=vm)

    if key == "rolling_average_spend":
        vm, chart = _rolling_average_spend_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, rolling_average_spend=vm, rolling_average_chart=chart)

    if key == "cumulative_ytd":
        vm, chart = _cumulative_ytd_vm(g.user.id)
        return render_template(REGISTRY[key].template, cumulative_ytd=vm, cumulative_ytd_chart=chart)

    if key == "spending_concentration":
        vm, chart = _spending_concentration_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, spending_concentration=vm, spending_concentration_chart=chart)

    if key == "new_merchant_detector":
        vm = _new_merchant_detector_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, new_merchant_detector=vm)

    if key == "daily_spend_average":
        vm, chart = _daily_spend_average_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, daily_spend_average=vm, daily_avg_chart=chart)

    if key == "weekend_splurge":
        vm, chart = _weekend_splurge_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, weekend_splurge=vm, weekend_splurge_chart=chart)

    if key == "payday_pattern":
        vm, chart = _payday_pattern_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, payday_pattern=vm, payday_pattern_chart=chart)

    abort(404)


@intelligence_bp.route("/report", endpoint="report")
def report_redirect():
    """Permanent redirect — /intelligence/report moved to /intelligence/dashboard."""
    return redirect(url_for("intelligence.dashboard"), 301)
