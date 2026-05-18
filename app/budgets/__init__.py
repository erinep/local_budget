"""Budgeting Module — Phase 4.

Owns public.budgets. Exposes get_budget_progress, get_budgets, propose_budgets,
upsert_budget, delete_budget, and apply_proposed_budgets via services.py.

All actuals are read exclusively through the Transaction Engine service layer
(ADR-0003). No direct access to public.transactions or any other module's tables.

ADR-0025: schema, service API, and route design.
"""
