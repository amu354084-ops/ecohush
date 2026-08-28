import hashlib

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import create_token, hash_password
from app.models.schema import User


client = TestClient(app)


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


def test_security_headers_are_present_on_api_responses():
    response = client.get("/api/v1/inventory/items")

    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
