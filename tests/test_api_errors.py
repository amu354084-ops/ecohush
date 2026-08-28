import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ERP_INITIAL_ADMIN_PASSWORD", "admin")
os.environ.setdefault("ERP_DISABLE_INITIAL_PASSWORD_CHANGE", "1")
os.environ.setdefault(
    "SQLITE_DB_PATH",
    str(Path(tempfile.gettempdir()) / f"erp_api_errors_{os.getpid()}.db"),
)

from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def app_lifespan():
    with client:
        yield


def admin_headers():
    response = client.post("/api/v1/login", json={"username": "admin", "password": "admin"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_checkout_invalid_payment_method_returns_validation_error():
    response = client.post(
        "/api/v1/sales/checkout",
        headers=admin_headers(),
        json={
            "counterparty_id": None,
            "items": [{"item_id": 1, "qty": "1", "unit_price": "10.00"}],
            "paid_amount": "10.00",
            "payment_method": "BITCOIN",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]
    assert any("Unsupported payment method" in item.get("msg", "") for item in response.json()["detail"])


def test_inventory_requires_authentication():
    response = client.get("/api/v1/inventory/items")

    assert response.status_code == 401


def test_shipment_invoice_not_found_returns_404():
    response = client.get("/api/v1/shipments/999999/invoice", headers=admin_headers())

    assert response.status_code == 404
    assert response.json() == {"detail": "Shipment not found"}
