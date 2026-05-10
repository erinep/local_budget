import io
import pytest
from app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def make_csv(rows: list[dict]) -> io.BytesIO:
    """Build a minimal valid CSV as a file-like object."""
    lines = ["Transaction Date,Description 1,CAD$"]
    for row in rows:
        lines.append(f"{row['date']},{row['desc']},{row['amount']}")
    content = "\n".join(lines).encode("latin1")
    buf = io.BytesIO(content)
    buf.name = "transactions.csv"
    return buf
