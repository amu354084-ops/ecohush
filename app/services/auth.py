from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from app.models.schema import User


DEFAULT_ENV_VALUES = {
    "ERP_AUTH_SECRET": secrets.token_hex(32),
    "ERP_INITIAL_ADMIN_PASSWORD": "",
    "ERP_CORS_ORIGINS": "http://localhost:1833,http://127.0.0.1:1833,http://localhost:8889,http://127.0.0.1:8889",
}


def ensure_env_file(project_root: Path | str | None = None) -> Path:
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
    env_file = root / ".env"
    existing_pairs: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("#") or "=" not in candidate:
                continue
            key, _, value = candidate.partition("=")
            existing_pairs[key.strip()] = value.strip().strip('"').strip("'")

    updates: list[str] = []
    for key, value in DEFAULT_ENV_VALUES.items():
        os.environ.setdefault(key, value)
        if key not in existing_pairs:
            updates.append(f"{key}={value}")
        elif existing_pairs[key] in ("", None):
            updates.append(f"{key}={value}")

    if updates:
        content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        lines = [line for line in content.splitlines() if line.strip()]
        lines.extend(updates)
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for key, value in DEFAULT_ENV_VALUES.items():
        os.environ.setdefault(key, value)

    return env_file


def _setting(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    env_file = ensure_env_file()
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, candidate = line.partition("=")
            if separator and key.strip() == name:
                return candidate.strip().strip('"').strip("'") or None
    return None


AUTH_SECRET = _setting("ERP_AUTH_SECRET") or DEFAULT_ENV_VALUES["ERP_AUTH_SECRET"]
TOKEN_TTL_SECONDS = 8 * 60 * 60


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"pbkdf2_sha256$120000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def create_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "password_marker": hashlib.sha256(user.password_hash.encode()).hexdigest(),
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(AUTH_SECRET.encode(), payload_text.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload_text}.{signature}".encode()).decode()


def decode_token(token: str) -> dict[str, object] | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload_text, signature = raw.rsplit(".", 1)
        expected = hmac.new(AUTH_SECRET.encode(), payload_text.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(payload_text)
        if not isinstance(payload, dict) or int(payload["exp"]) <= int(time.time()):
            return None
        return payload
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        return None
