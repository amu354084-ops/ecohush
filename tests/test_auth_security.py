import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import create_token, hash_password
from app.models.schema import User
from app.api.auth_dependencies import user_permissions
from app.api.orders_api import build_order_query


client = TestClient(app)


def test_order_access_requires_explicit_permission_for_non_admins():
    courier = User(username="permission-courier", password_hash="hash", role="COURIER", permissions=None)
    explicitly_allowed = User(
        username="allowed-courier",
        password_hash="hash",
        role="COURIER",
        permissions='["orders"]',
    )
    admin = User(username="permission-admin", password_hash="hash", role="ADMIN", permissions="[]")

    assert "orders" not in user_permissions(courier)
    assert "orders" in user_permissions(explicitly_allowed)
    assert "orders" in user_permissions(admin)


def test_password_change_invalidates_existing_token(monkeypatch):
    user = User(id=7, username="security-user", password_hash=hash_password("old-pass"), role="ADMIN")
    token = create_token(user)
    user.password_hash = hash_password("new-pass")

    from app.services import auth

    decoded = auth.decode_token(token)
    assert decoded is not None
    assert decoded["password_marker"] != hashlib.sha256(user.password_hash.encode()).hexdigest()


def test_login_rate_limit_blocks_repeated_failures():
    for _ in range(10):
        response = client.post("/api/v1/login", json={"username": "unknown-security-user", "password": "wrong"})
        assert response.status_code == 401

    response = client.post("/api/v1/login", json={"username": "unknown-security-user", "password": "wrong"})
    assert response.status_code == 429


def test_simple_users_default_to_own_orders_only():
    user = User(id=7, username="simple-worker", password_hash="hash", role="WORKER", permissions='["orders"]')

    query = build_order_query(status=None, seller_id=None, user=user)
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "courier_id = 7" in compiled

    with pytest.raises(ValueError, match="своим заказам"):
        build_order_query(status=None, seller_id=9, user=user)


def test_security_headers_are_present_on_api_responses():
    response = client.get("/api/v1/inventory/items")

    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
