import io
import pytest
from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client


def make_csv(rows: list[dict]) -> io.BytesIO:
    """Build a minimal valid CSV as a file-like object."""
    lines = ["Transaction Date,Description 1,CAD$"]
    for row in rows:
        lines.append(f"{row['date']},{row['desc']},{row['amount']}")
    content = "\n".join(lines).encode("latin1")
    buf = io.BytesIO(content)
    buf.name = "transactions.csv"
    return buf
