"""Database engine singleton for Local Budget Parser.

ADR-0002: Supabase is the PostgreSQL host. All database access outside
app/auth/services.py uses standard SQLAlchemy + psycopg2 — no Supabase SDK.

The engine is lazily created on first call and reused for the lifetime of the
process. In tests, DATABASE_URL should be set to a test database; the
conftest.py is responsible for schema setup and teardown.
"""

import os
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine, creating it on first call.

    Reads DATABASE_URL from the environment. Raises RuntimeError if the
    variable is not set; callers in tests should mock this function or set
    DATABASE_URL before importing.
    """
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Set it to a PostgreSQL connection string."
            )
        # pool_pre_ping ensures stale connections are detected and recycled
        # automatically, which matters on Supabase's connection-pooler.
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine
