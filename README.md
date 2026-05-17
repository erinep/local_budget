# Local Budget Parser

[![Tests](https://github.com/erinep/local_budget/actions/workflows/tests.yml/badge.svg)](https://github.com/erinep/local_budget/actions/workflows/tests.yml)
[![Deploy](https://github.com/erinep/local_budget/actions/workflows/deploy.yml/badge.svg)](https://github.com/erinep/local_budget/actions/workflows/deploy.yml)

A Flask app that turns exported bank transaction CSVs into a visual spending report, with monthly breakdowns, category charts, and drillable transaction lists.

## Usage

Upload a CSV export from your bank. The app categorizes each transaction, filters out transfers and payments, and generates:

- Monthly spending trend chart
- Overall category share (donut chart, drillable to transactions)
- Month-by-month category breakdown
- Merchant to category mapping

### Expected CSV columns

| Column | Description |
|---|---|
| `Transaction Date` | Used for monthly grouping |
| `Description 1` | Merchant name, used for categorization |
| `CAD$` | Transaction amount |

## Category Rules

Matching is substring-based and case-insensitive.

- `generic_categories.json` contains shared keyword rules and seeds new accounts on first login (see `seed_defaults` in `app/account_settings/services.py`).
- Per-user category overrides live in the database and are managed entirely through the Account Settings UI (`/account-settings/categories`).

Examples: `NO FRILLS` → Food, `AIRBNB` → Travel, `UBER` → Transport. Anything unmatched falls back to Slush Fund.

### Migrating an existing `custom_categories.json`

Phase 1 and earlier loaded a `custom_categories.json` file at the repo root. That file is no longer read at startup. If you have one, import it via the UI:

1. Sign in.
2. Go to `/account-settings/categories` and use the **Import** action (`POST /account-settings/import`).
3. Upload the JSON file. It is merged into your existing categories.

A reference file showing the expected shape lives at `samples/custom_categories.example.json`.

## Development

**Install dependencies**
```powershell
.\venv\Scripts\Activate.ps1 # activate virtual environment (if created - otherwise 'run python3 -m venv venv' to create it)
pip install -r requirements-dev.txt
```

**Run locally (with venv active)**
```powershell
flask --app wsgi:app run
```
Then open `http://127.0.0.1:5000`.

**Run tests**
```powershell
pytest -v
```

**Run with debug mode**
```powershell
$env:FLASK_DEBUG = "true"
python app.py
```

## Deployment

The app is deployed on Render via two separate workflows:

- **Tests** — runs on every PR and every push to `main`. Must pass before a PR can be merged.
- **Deploy** — runs only on merge to `main`, triggering a Render deploy. Runs independently of tests; a failing deploy does not retroactively affect the test badge.

Debug mode is always off in production.

## Project Structure

```
app.py                  Flask app and data processing
templates/              Jinja HTML templates
static/                 CSS and chart rendering (JS)
tests/                  pytest suite
generic_categories.json Shared category keyword rules
render.yaml             Render deployment config
requirements.txt        Production dependencies
requirements-dev.txt    Development and test dependencies
```
