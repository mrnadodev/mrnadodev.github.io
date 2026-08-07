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
    assert "SUREBET" in resp.text
    assert "Arbitrage Scanner Pro" in resp.text
    assert "Opportunités Arbitrage Actives" in resp.text
    assert "/api/scan" in resp.text  # le scan live est cable


def test_scan_endpoint_shape(client, monkeypatch):
    """L'endpoint de scan renvoie stats + opportunites, meme si les books sont
    injoignables depuis l'environnement de test (scrapers mockes a vide)."""
    import surebet.dashboard.app as app_mod

    def no_scrapers(exclude):
        return []

    monkeypatch.setattr(app_mod, "_build_fast_scrapers", no_scrapers)
    resp = client.get("/api/scan?sport=football&min_profit=0")
    assert resp.status_code == 200
    body = resp.json()
    assert "stats" in body and "opportunities" in body
    assert body["stats"]["matches_analysed"] == 0
    assert body["opportunities"] == []


def test_scan_includes_lakay_only_when_requested(client, monkeypatch):
    """Paryaj Lakay (lent) n'est scrape que si include_lakay=true."""
    import surebet.dashboard.app as app_mod

    monkeypatch.setattr(app_mod, "_build_fast_scrapers", lambda exclude: [])
    calls = {"lakay": 0}

    async def fake_lakay(sport):
        calls["lakay"] += 1
        return []

    monkeypatch.setattr(app_mod, "_scrape_lakay", fake_lakay)

    client.get("/api/scan?sport=football")  # defaut : sans Lakay
    assert calls["lakay"] == 0

    client.get("/api/scan?sport=football&include_lakay=true")
    assert calls["lakay"] == 1


def test_scan_excludes_lakay_even_if_requested(client, monkeypatch):
    """Si Paryaj Lakay est dans la liste d'exclusion, on ne le scrape pas."""
    import surebet.dashboard.app as app_mod

    monkeypatch.setattr(app_mod, "_build_fast_scrapers", lambda exclude: [])
    calls = {"lakay": 0}

    async def fake_lakay(sport):
        calls["lakay"] += 1
        return []

    monkeypatch.setattr(app_mod, "_scrape_lakay", fake_lakay)
    client.get("/api/scan?sport=football&include_lakay=true&exclude=Paryaj Lakay")
    assert calls["lakay"] == 0


def test_index_exposes_lakay_toggle(client):
    resp = client.get("/")
    assert "f-lakay" in resp.text
    assert "Paryaj Lakay" in resp.text


def test_index_exposes_funbet_section(client):
    resp = client.get("/")
    assert "FunBets" in resp.text
    assert "/api/funbets" in resp.text


def test_funbets_endpoint_prices_against_xbet(client, monkeypatch):
    """L'endpoint FunBet chiffre les jambes disponibles et signale les autres."""
    import surebet.dashboard.app as app_mod
    from surebet.funbet.parser import parse_funbet

    async def fake_funbets():
        return [parse_funbet("Real Madrid - Barcelona",
                             "Real Madrid gagne & obtient 8 corners ou +", 6.0)]

    monkeypatch.setattr(app_mod, "_scrape_lakay_funbets", fake_funbets)

    # 1xBet a la victoire mais pas les corners -> chiffrage partiel
    from datetime import datetime, timezone

    from surebet.normalizer.schema import Odd, make_match_id

    day = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
    mid = make_match_id("Real Madrid", "Barcelona", day)

    class FakeXBet:
        bookmaker_name = "1xBet"

        def __init__(self, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def scrape(self, sport):
            return [Odd(bookmaker="1xBet", sport="football", competition="X", match_id=mid,
                        home_team="Real Madrid", away_team="Barcelona", start_time=day,
                        market_type="1x2", n_outcomes=3, selection="home", line=None,
                        team_scope=None, odds=1.8, url="https://x/e",
                        scraped_at=datetime.now(timezone.utc))]

    monkeypatch.setattr("surebet.scrapers.xbet.XBetScraper", FakeXBet)

    body = client.get("/api/funbets").json()
    assert len(body["funbets"]) == 1
    fb = body["funbets"][0]
    assert fb["boosted_odds"] == 6.0
    assert fb["complete"] is False          # corners non chiffrables
    assert fb["edge_pct"] is None
    # la jambe victoire est chiffree (1.8), la jambe corners signalee
    priced = [l for l in fb["legs"] if l["fair_odds"] is not None]
    assert any(l["fair_odds"] == 1.8 for l in priced)


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


def test_ai_success_rate_helper(monkeypatch):
    import surebet.dashboard.app as app_mod

    # Seuil explicite : le test ne doit pas dependre du .env ambiant.
    monkeypatch.setattr(app_mod.settings, "min_score_alert", 70)

    class Row:
        def __init__(self, score):
            self.score_ia = score

    rows = [Row(88), Row(60), Row(90), Row(None)]
    rate = app_mod._ai_match_success_rate(rows)
    assert rate == pytest.approx(66.7, abs=0.1)  # 2 sur 3 scored >= 70
