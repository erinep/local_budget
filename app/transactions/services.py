"""Transaction Engine service layer — pure helpers and persisted read/write API.

This module is the single source of truth for transaction data. No other module
may query the public.transactions, public.uploads, or public.accounts tables
directly. Cross-module access to transaction data is exclusively through the
functions exported here. Direct queries from any other module are bugs, not
shortcuts (ADR-0003, ADR-0004).

Public API (ADR-0017):
  TransactionFilters  — filter dataclass for get_transactions
  TransactionPage     — paginated result container
  Transaction         — single exported row shape
  TransactionNotFound — raised when no row matches (user_id, transaction_id)
  get_transactions(user_id, filters) -> TransactionPage
  get_transaction(user_id, transaction_id) -> Transaction

Internal columns never exported to callers:
  fingerprint    — SHA-256 dedup hash (ADR-0013); internal to upload pipeline
  source_file_id — upload provenance; internal to pipeline

Referenced ADRs:
  ADR-0003: service-layer-only module communication
  ADR-0013: two-layer hash idempotency strategy
  ADR-0014: multi-account per user; account_id in fingerprint namespace
  ADR-0015: hard cascade on user deletion
  ADR-0016: Phase 3a schema specification
  ADR-0017: Transaction Engine read API contract

PII discipline: never log raw transaction descriptions, amounts, filenames, or
fingerprints. Use structured logging with scrubbed keys only.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Callable
from uuid import UUID

import pandas as pd
from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NON_TRACKED_KEYWORDS = [
    "PAYMENT",
    "TRANSFER",
    "E-TRANSFER",
    "AUTOPAY",
    "THANK YOU",
    "CREDIT CARD PAYMENT",
]


# ---------------------------------------------------------------------------
# Legacy pure-function helpers (kept for backward compatibility)
# ---------------------------------------------------------------------------

def make_categorizer(custom_map: dict, generic_map: dict) -> Callable[[str], str]:
    """Return a single-argument callable suitable for DataFrame.apply.

    ADR 0005 — Option B (factory closure). The returned closure carries its own
    maps so the call site in the route handler does not change when map loading
    moves to the database in Phase 1.
    """
    def categorize(desc: str) -> str:
        desc = str(desc).upper()
        for category_map in (custom_map, generic_map):
            for category, keywords in category_map.items():
                for keyword in keywords:
                    if str(keyword).upper() in desc:
                        return category
        return "Slush Fund"

    return categorize


def net_amount(row) -> float:
    """Return the net spend for a transaction row.

    Payments, transfers, and other non-tracked keywords are zeroed out.
    Money-out (negative CAD$) becomes positive net spend.
    Money-in (positive CAD$, e.g. refunds) becomes negative net.
    """
    amount = row["CAD$"]
    desc = str(row["Description 1"]).upper()

    if any(keyword in desc for keyword in NON_TRACKED_KEYWORDS):
        return 0
    if amount > 0:
        return -amount
    return abs(amount)


def series_to_chart_data(series) -> list:
    """Convert a pandas Series of category totals to chart-ready dicts."""
    cleaned = series[series > 0].sort_values(ascending=False)
    return [
        {"label": str(label), "value": round(float(value), 2)}
        for label, value in cleaned.items()
    ]


def serialize_transactions(frame, *, sort_by) -> list:
    """Serialize a transactions DataFrame slice to a list of dicts for templates."""
    return (
        frame[["Transaction Date", "Description 1", "Category", "Net"]]
        .sort_values(sort_by, ascending=[False] * len(sort_by))
        .assign(
            **{
                "Transaction Date": lambda data: data["Transaction Date"].dt.strftime("%b %d, %Y"),
                "Net": lambda data: data["Net"].round(2),
            }
        )
        .rename(columns={"Description 1": "Description"})
        .to_dict("records")
    )


# ---------------------------------------------------------------------------
# Public API types (ADR-0017)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransactionFilters:
    """Filter parameters for get_transactions.

    All fields are optional; defaults produce the most-recent 50 transactions.
    See ADR-0017 for field-by-field semantics and mutual exclusion rules.
    """
    date_from: date | None = None
    date_to: date | None = None
    category_id: UUID | None = None
    account_id: UUID | None = None
    search: str | None = None
    uncategorized_only: bool = False
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class Transaction:
    """A single exported transaction row. Narrower than the DB table by design.

    Excluded: fingerprint (internal dedup, ADR-0013), source_file_id (upload
    provenance, internal), user_id (redundant given the call parameter).
    """
    id: UUID
    account_id: UUID
    account_name: str
    date: date
    description: str
    amount: Decimal
    category_id: UUID | None
    category_name: str | None
    created_at: datetime  # UTC per ADR-0001


@dataclass(frozen=True)
class TransactionPage:
    """Paginated result container for get_transactions."""
    items: list[Transaction]
    total_count: int
    limit: int
    offset: int


class TransactionNotFound(Exception):
    """Raised when no row matches (user_id, transaction_id) or belongs to a different user.

    There is no Forbidden variant — cross-user lookups are indistinguishable
    from non-existent rows by design (ADR-0017, tenant isolation).
    """


# ---------------------------------------------------------------------------
# Internal upload pipeline helpers
# ---------------------------------------------------------------------------

def _get_or_create_default_account(user_id: str) -> str:
    """Find any active account for user_id or create the default one.

    Uses ON CONFLICT DO NOTHING so concurrent inserts are safe.
    Returns the account UUID as a lowercase str.
    """
    engine = get_engine()
    with engine.begin() as conn:
        # Check for any existing active account first.
        row = conn.execute(
            text(
                "SELECT id FROM public.accounts"
                " WHERE user_id = :uid AND is_active = true"
                " LIMIT 1"
            ),
            {"uid": user_id},
        ).fetchone()
        if row is not None:
            return str(row[0])

        # None found — insert the default, ignore conflict if a race occurs.
        result = conn.execute(
            text(
                "INSERT INTO public.accounts (user_id, name, kind, currency)"
                " VALUES (:uid, 'Default', 'checking', 'CAD')"
                " ON CONFLICT (user_id, name) DO NOTHING"
                " RETURNING id"
            ),
            {"uid": user_id},
        ).fetchone()

        if result is not None:
            return str(result[0])

        # Rare race: another request inserted before us; fetch it.
        row = conn.execute(
            text(
                "SELECT id FROM public.accounts"
                " WHERE user_id = :uid AND name = 'Default'"
                " LIMIT 1"
            ),
            {"uid": user_id},
        ).fetchone()
        return str(row[0])


def _compute_fingerprint(
    user_id: str,
    account_id: str,
    iso_date: str,
    description_normalized: str,
    amount_signed_2dp: str,
    within_file_seq: int,
) -> bytes:
    """Compute SHA-256 fingerprint for one transaction row per ADR-0013.

    All fields joined by ASCII Unit Separator (0x1F).
    Returns raw 32-byte digest (BYTEA).
    """
    canonical = "\x1f".join([
        user_id.lower(),
        account_id.lower(),
        iso_date,
        description_normalized,
        amount_signed_2dp,
        str(within_file_seq),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def _process_upload(
    user_id: str,
    filename: str,
    file_bytes: bytes,
    df: pd.DataFrame,
) -> dict:
    """Persist a CSV upload and its transactions to the database.

    This is the upload pipeline. It is internal — callers are route handlers
    in this module only.

    Args:
        user_id:    Authenticated user's UUID string.
        filename:   Original filename (stored verbatim in uploads.filename).
        file_bytes: Raw CSV bytes (used for file-level hash, ADR-0013 layer 1).
        df:         Pre-processed DataFrame with columns:
                    "Transaction Date" (datetime), "Description 1" (str),
                    "CAD$" (float), "Category" (str), "Net" (float).
                    Must already have Net==0 rows filtered out.

    Returns:
        {
            "upload_id": str UUID,
            "new_count": int,
            "dup_count": int,
            "already_uploaded": bool,
        }
    """
    # Layer 1: file-level hash short-circuit (ADR-0013).
    file_hash = hashlib.sha256(file_bytes).digest()

    engine = get_engine()
    with engine.connect() as conn:
        existing = conn.execute(
            text(
                "SELECT id FROM public.uploads"
                " WHERE user_id = :uid AND file_hash = :fh"
            ),
            {"uid": user_id, "fh": file_hash},
        ).fetchone()

    if existing is not None:
        return {
            "upload_id": str(existing[0]),
            "new_count": 0,
            "dup_count": 0,
            "already_uploaded": True,
        }

    # Get or create the default account for this user.
    account_id = _get_or_create_default_account(user_id)

    # Resolve category names to IDs in one query.
    category_names = df["Category"].dropna().unique().tolist()
    cat_id_map: dict[str, str] = {}  # name → str UUID
    if category_names:
        engine2 = get_engine()
        with engine2.connect() as conn:
            cat_rows = conn.execute(
                text(
                    "SELECT id, name FROM public.categories"
                    " WHERE user_id = :uid"
                ),
                {"uid": user_id},
            ).fetchall()
        for row in cat_rows:
            cat_id_map[row[1]] = str(row[0])

    # Compute within-file sequence numbers per (date, desc_norm, amount) group.
    # This preserves genuine same-day duplicate rows (ADR-0013).
    seq_counters: dict[tuple, int] = {}
    fingerprints: list[bytes] = []

    for _, row_data in df.iterrows():
        tx_date = row_data["Transaction Date"]
        iso_date = tx_date.strftime("%Y-%m-%d") if hasattr(tx_date, "strftime") else str(tx_date)[:10]

        desc_raw = str(row_data["Description 1"])
        desc_norm = " ".join(desc_raw.strip().split()).casefold()

        amount_val = float(row_data["CAD$"])
        amount_str = f"{amount_val:.2f}"

        group_key = (iso_date, desc_norm, amount_str)
        seq = seq_counters.get(group_key, 0)
        seq_counters[group_key] = seq + 1

        fp = _compute_fingerprint(
            user_id=user_id,
            account_id=account_id,
            iso_date=iso_date,
            description_normalized=desc_norm,
            amount_signed_2dp=amount_str,
            within_file_seq=seq,
        )
        fingerprints.append(fp)

    # Persist: insert uploads row then transactions rows inside one transaction.
    new_count = 0
    total_rows = len(df)

    with engine.begin() as conn:
        # Insert uploads row.
        upload_result = conn.execute(
            text(
                "INSERT INTO public.uploads"
                " (user_id, account_id, filename, file_hash, row_count)"
                " VALUES (:uid, :aid, :fn, :fh, :rc)"
                " RETURNING id"
            ),
            {
                "uid": user_id,
                "aid": account_id,
                "fn": filename,
                "fh": file_hash,
                "rc": total_rows,
            },
        )
        upload_id = str(upload_result.fetchone()[0])

        # Insert transactions, deduplicating at row level.
        for i, (_, row_data) in enumerate(df.iterrows()):
            tx_date = row_data["Transaction Date"]
            iso_date = tx_date.strftime("%Y-%m-%d") if hasattr(tx_date, "strftime") else str(tx_date)[:10]

            desc_raw = str(row_data["Description 1"])
            amount_val = float(row_data["CAD$"])
            category_name = row_data.get("Category")
            cat_id = cat_id_map.get(category_name) if category_name else None

            result = conn.execute(
                text(
                    "INSERT INTO public.transactions"
                    " (user_id, account_id, source_file_id, date, description,"
                    "  amount, category_id, fingerprint)"
                    " VALUES (:uid, :aid, :sfid, :dt, :desc, :amt, :cat, :fp)"
                    " ON CONFLICT (user_id, fingerprint) DO NOTHING"
                    " RETURNING id"
                ),
                {
                    "uid": user_id,
                    "aid": account_id,
                    "sfid": upload_id,
                    "dt": iso_date,
                    "desc": desc_raw,
                    "amt": amount_val,
                    "cat": cat_id,
                    "fp": fingerprints[i],
                },
            )
            if result.fetchone() is not None:
                new_count += 1

    dup_count = total_rows - new_count
    return {
        "upload_id": upload_id,
        "new_count": new_count,
        "dup_count": dup_count,
        "already_uploaded": False,
    }


# ---------------------------------------------------------------------------
# Public read API (ADR-0017)
# ---------------------------------------------------------------------------

def get_transactions(
    user_id: str,
    filters: TransactionFilters | None = None,
) -> TransactionPage:
    """Return a paginated page of transactions for user_id.

    Args:
        user_id: Authenticated user's UUID string. Required; never implicit.
        filters: Optional filter dataclass. None is equivalent to TransactionFilters().

    Returns:
        TransactionPage with items, total_count, limit, offset.

    Raises:
        ValueError: for invalid filter combinations (see ADR-0017 error model).
    """
    if filters is None:
        filters = TransactionFilters()

    # --- Validate filters before any DB query ---
    if not (1 <= filters.limit <= 200):
        raise ValueError("limit must be between 1 and 200")
    if filters.offset < 0:
        raise ValueError("offset must be >= 0")
    if filters.date_from is not None and filters.date_to is not None:
        if filters.date_from > filters.date_to:
            raise ValueError("date_from must be <= date_to")
    if filters.category_id is not None and filters.uncategorized_only:
        raise ValueError("category_id and uncategorized_only are mutually exclusive")

    # Normalise empty search to None.
    search = filters.search if filters.search else None

    # --- Build WHERE clause predicates ---
    where_parts = ["t.user_id = :user_id"]
    params: dict = {"user_id": user_id}

    if filters.date_from is not None:
        where_parts.append("t.date >= :date_from")
        params["date_from"] = filters.date_from

    if filters.date_to is not None:
        where_parts.append("t.date <= :date_to")
        params["date_to"] = filters.date_to

    if filters.category_id is not None:
        where_parts.append("t.category_id = :category_id")
        params["category_id"] = str(filters.category_id)

    if filters.account_id is not None:
        where_parts.append("t.account_id = :account_id")
        params["account_id"] = str(filters.account_id)

    if filters.uncategorized_only:
        where_parts.append("t.category_id IS NULL")

    if search is not None:
        where_parts.append("LOWER(t.description) LIKE LOWER(:search_pattern)")
        params["search_pattern"] = f"%{search}%"

    where_clause = " AND ".join(where_parts)

    base_from = (
        "FROM public.transactions t"
        " LEFT JOIN public.categories c ON c.id = t.category_id"
        " JOIN public.accounts a ON a.id = t.account_id"
    )

    count_sql = text(f"SELECT COUNT(*) {base_from} WHERE {where_clause}")

    page_sql = text(
        f"SELECT t.id, t.account_id, a.name AS account_name,"
        f" t.date, t.description, t.amount,"
        f" t.category_id, c.name AS category_name, t.created_at"
        f" {base_from}"
        f" WHERE {where_clause}"
        f" ORDER BY t.date DESC, t.created_at DESC, t.id DESC"
        f" LIMIT :limit OFFSET :offset"
    )
    params["limit"] = filters.limit
    params["offset"] = filters.offset

    engine = get_engine()
    with engine.connect() as conn:
        total_count = conn.execute(count_sql, params).scalar()
        rows = conn.execute(page_sql, params).fetchall()

    items = [
        Transaction(
            id=UUID(str(row[0])),
            account_id=UUID(str(row[1])),
            account_name=row[2],
            date=row[3],
            description=row[4],
            amount=Decimal(str(row[5])),
            category_id=UUID(str(row[6])) if row[6] is not None else None,
            category_name=row[7],
            created_at=row[8],
        )
        for row in rows
    ]

    return TransactionPage(
        items=items,
        total_count=int(total_count),
        limit=filters.limit,
        offset=filters.offset,
    )


def get_transaction(user_id: str, transaction_id: UUID) -> Transaction:
    """Return a single transaction by ID, scoped to user_id.

    Raises:
        TransactionNotFound: if no row matches (user_id, transaction_id),
            including the case where the row exists but belongs to a
            different user (tenant isolation per ADR-0017).
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT t.id, t.account_id, a.name AS account_name,"
                " t.date, t.description, t.amount,"
                " t.category_id, c.name AS category_name, t.created_at"
                " FROM public.transactions t"
                " JOIN public.accounts a ON a.id = t.account_id"
                " LEFT JOIN public.categories c ON c.id = t.category_id"
                " WHERE t.id = :txn_id AND t.user_id = :user_id"
            ),
            {"txn_id": str(transaction_id), "user_id": user_id},
        ).fetchone()

    if row is None:
        raise TransactionNotFound(
            f"No transaction found for the given id and user."
        )

    return Transaction(
        id=UUID(str(row[0])),
        account_id=UUID(str(row[1])),
        account_name=row[2],
        date=row[3],
        description=row[4],
        amount=Decimal(str(row[5])),
        category_id=UUID(str(row[6])) if row[6] is not None else None,
        category_name=row[7],
        created_at=row[8],
    )
