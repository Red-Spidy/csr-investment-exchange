import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.util import camel, inr, num, shape


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (2_400_000, "₹24,00,000"),
        (800_000, "₹8,00,000"),
        (999, "₹999"),
        (12_345, "₹12,345"),
        (10_000_000, "₹1,00,00,000"),
        (333_333.33, "₹3,33,333"),
        (-1_500, "-₹1,500"),
        (0, "₹0"),
    ],
)
def test_inr_groups_like_the_frontend(amount, text):
    assert inr(amount) == text


@pytest.mark.parametrize(("value", "text"), [(3.1, "3.1"), (100_000.0, "100000"), (1e6, "1000000"), (0.5, "0.5")])
def test_num_never_uses_an_exponent(value, text):
    assert num(value) == text


def test_shape_camelizes_and_renames():
    assert camel("mandated_csr_budget") == "mandatedCsrBudget"
    assert shape({"txn_type": "lock", "created_at": 1}, txn_type="type") == {"type": "lock", "createdAt": 1}


def test_an_unreachable_database_is_503_not_a_crash():
    app = create_app("postgresql://csr:csr@127.0.0.1:1/none", allow_reset=False, pool_timeout=1)
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 503
        assert c.get("/api/companies").status_code == 503
        assert c.post("/api/commitments", json={"companyId": 1, "projectId": 2}).status_code == 503
