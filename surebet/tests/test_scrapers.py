"""Tests des scrapers hors-ligne (spec MISSION §3, §9).

- 1xBet : parsing du JSON LineFeed reel (fixture) sans reseau (respx mock).
- Paryaj Lakay : parsing du HTML evenement REEL capture en recon (fixture),
  via le pipeline pur parsing.py (aucun navigateur requis).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from surebet.scrapers.parsing import (
    MatchMeta,
    extract_markets_from_html,
    parse_odds_value,
    raw_markets_to_odds,
)
from surebet.scrapers.xbet import XBetScraper

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseOddsValue:
    def test_french_comma_decimal(self):
        assert parse_odds_value("1,57") == pytest.approx(1.57)

    def test_integer_odds(self):
        assert parse_odds_value("13") == pytest.approx(13.0)

    def test_rejects_below_one(self):
        assert parse_odds_value("0,95") is None

    def test_rejects_garbage(self):
        assert parse_odds_value("N/A") is None


class TestParyajLakayFixture:
    """Parsing du HTML evenement REEL (Club Bolivar vs Gremio) capture en recon."""

    def _meta(self) -> MatchMeta:
        return MatchMeta(
            bookmaker="Paryaj Lakay",
            sport="football",
            competition="Copa Sudamericana",
            home_team="Club Bolivar",
            away_team="Gremio Porto Alegrense",
            start_time=datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc),
            url="https://www.paryajlakay.com/sports/event/club-bolivar-gremio-m76289162",
        )

    def _odds(self):
        html = (FIXTURES / "paryajlakay_event.html").read_text(encoding="utf-8")
        markets = extract_markets_from_html(html)
        return markets, raw_markets_to_odds(markets, self._meta())

    def test_extracts_three_markets(self):
        markets, _ = self._odds()
        titles = {m.title for m in markets}
        assert "Résultat du match" in titles
        assert "Nombre de buts" in titles
        assert "Total de buts de Club Bolivar" in titles

    def test_1x2_parsed_with_three_outcomes(self):
        _, odds = self._odds()
        x2 = [o for o in odds if o.market_type == "1x2"]
        assert {o.selection for o in x2} == {"home", "draw", "away"}
        home = next(o for o in x2 if o.selection == "home")
        assert home.odds == pytest.approx(1.57)
        assert home.n_outcomes == 3

    def test_goals_total_over_under_parsed(self):
        _, odds = self._odds()
        goals = [o for o in odds if o.market_type == "goals_total"]
        over_25 = next(o for o in goals if o.selection == "over" and o.line == 2.5)
        under_25 = next(o for o in goals if o.selection == "under" and o.line == 2.5)
        assert over_25.odds == pytest.approx(1.78)
        assert under_25.odds == pytest.approx(1.90)

    def test_team_scoped_goals_get_team_scope(self):
        _, odds = self._odds()
        team_goals = [o for o in odds if o.market_type == "goals_team"]
        assert team_goals, "Le marche 'Total de buts de Club Bolivar' doit produire goals_team"
        assert all(o.team_scope == "home" for o in team_goals)


@pytest.mark.asyncio
@respx.mock
async def test_xbet_scraper_parses_line_feed():
    payload = json.loads((FIXTURES / "xbet_get1x2.json").read_text(encoding="utf-8"))
    respx.get(url__regex=r".*LineFeed/Get1x2_VZip.*").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with XBetScraper(base_url="https://ht.1xbet.com") as scraper:
        odds = await scraper.scrape("football")

    x2 = [o for o in odds if o.market_type == "1x2"]
    assert len(x2) == 6  # 2 matchs x 3 issues
    bolivar_home = next(
        o for o in x2 if o.home_team == "Club Bolivar" and o.selection == "home"
    )
    assert bolivar_home.odds == pytest.approx(1.57)
    assert bolivar_home.bookmaker == "1xBet"

    totals = [o for o in odds if o.market_type == "goals_total"]
    assert len(totals) == 2
    assert {o.selection for o in totals} == {"over", "under"}


@pytest.mark.asyncio
@respx.mock
async def test_xbet_scraper_retries_then_raises_on_persistent_failure():
    from surebet.scrapers.base import ScraperUnavailableError

    respx.get(url__regex=r".*LineFeed.*").mock(return_value=httpx.Response(503))
    async with XBetScraper(
        base_url="https://ht.1xbet.com", max_retries=2, base_delay=0.01, use_browser_fallback=False
    ) as scraper:
        with pytest.raises(ScraperUnavailableError):
            await scraper.scrape("football")
