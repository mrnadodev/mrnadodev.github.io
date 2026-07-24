"""Tests du dashboard FastAPI (spec MISSION §8)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "dash.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    # recharger settings + app avec la DB temporaire
    import importlib

    import surebet.config as config_mod
    importlib.reload(config_mod)
    import surebet.dashboard.app as app_mod
    importlib.reload(app_mod)

    import asyncio

    from surebet.storage.db import init_db

    asyncio.run(init_db(app_mod._engine))
    return TestClient(app_mod.app)


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Surebet" in resp.text
    assert "Courbe de bankroll" in resp.text


def test_opportunities_fragment_empty(client):
    resp = client.get("/fragments/opportunities")
    assert resp.status_code == 200
    assert "Aucune opportunité" in resp.text


def test_api_opportunities_empty(client):
    resp = client.get("/api/opportunities")
    assert resp.status_code == 200
    assert resp.json() == []


def test_bankroll_svg_helper():
    import surebet.dashboard.app as app_mod

    svg = app_mod._bankroll_svg([
        {"t": "2026-07-23T10:00:00", "cumulative_profit": 1000.0},
        {"t": "2026-07-23T10:05:00", "cumulative_profit": 2500.0},
    ])
    assert "<svg" in svg and "polyline" in svg


def test_ai_success_rate_helper():
    import surebet.dashboard.app as app_mod

    class Row:
        def __init__(self, score):
            self.score_ia = score

    rows = [Row(88), Row(60), Row(90), Row(None)]
    rate = app_mod._ai_match_success_rate(rows)
    assert rate == pytest.approx(66.7, abs=0.1)  # 2 sur 3 scored >= 70
