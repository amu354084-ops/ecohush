import pytest

from app.main import get_server_settings


def test_web_server_defaults_use_public_host(monkeypatch):
    monkeypatch.delenv("ERP_HOST", raising=False)
    monkeypatch.delenv("ERP_SERVER_PORT", raising=False)

    settings = get_server_settings()

    assert settings["host"] == "0.0.0.0"
    assert settings["port"] == 1833


@pytest.mark.asyncio
async def test_health_endpoint_reports_database_readiness():
    from app.main import health

    assert await health() == {"status": "ok"}
