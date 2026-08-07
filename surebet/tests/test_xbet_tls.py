"""Tests du scraper 1xBet (empreinte TLS Chrome via curl_cffi).

Le payload de reference reproduit la structure reelle du flux LineFeed
(juillet 2026) : marches dans `E[]`, identifies par groupe `G` et type `T`,
`C` = cote, `P` = ligne. Aucun reseau : le fetch est monkeypatche.
"""
import pytest

from surebet.scrapers.base import ScraperUnavailableError
from surebet.scrapers.xbet import EXCLUDED_GROUPS, MARKET_MAP, XBET_PARTNER, XBetScraper

LIVE_SHAPED = {
    "Success": True,
    "Value": [
        {
            "I": 123456,
            "O1": "CSKA Moscou",
            "O2": "Baltika Kaliningrad",
            "L": "Championnat de Russie",
            "S": 1784912400,
            "E": [
                {"G": 1, "T": 1, "C": 2.025},
                {"G": 1, "T": 2, "C": 3.165},
                {"G": 1, "T": 3, "C": 4.12},
                {"G": 17, "T": 9, "P": 2.5, "C": 2.17},
                {"G": 17, "T": 10, "P": 2.5, "C": 1.69},
                {"G": 15, "T": 11, "P": 1.5, "C": 2.12},
                {"G": 15, "T": 12, "P": 1.5, "C": 1.70},
                {"G": 62, "T": 13, "P": 0.5, "C": 1.54},
                {"G": 62, "T": 14, "P": 0.5, "C": 2.36},
                {"G": 19, "T": 180, "C": 1.89},
                {"G": 19, "T": 181, "C": 1.83},
                # Double chance : issues qui se recouvrent -> doit etre ignore
                {"G": 8, "T": 4, "C": 1.263},
                {"G": 8, "T": 5, "C": 1.387},
                {"G": 8, "T": 6, "C": 1.821},
                # cote invalide
                {"G": 1, "T": 1, "C": 1.0},
                # groupe inconnu
                {"G": 9999, "T": 1, "C": 3.0},
            ],
        }
    ],
}


@pytest.fixture
def scraper(monkeypatch):
    s = XBetScraper()

    async def fake_fetch(url):
        return LIVE_SHAPED

    monkeypatch.setattr(s, "_fetch", fake_fetch)
    return s


class TestFeedUrl:
    def test_uses_service_api_route(self):
        url = XBetScraper()._feed_url(1)
        assert "/service-api/LineFeed/Get1x2_VZip" in url

    def test_uses_sports_plural_parameter(self):
        """`sportId=` renvoie 404 "Fail route" ; le bon parametre est `sports=`."""
        url = XBetScraper()._feed_url(1)
        assert "sports=1" in url
        assert "sportId=" not in url

    def test_uses_partner_151(self):
        """partner=1 -> 406 NotAcceptableException ; partner=151 -> 200."""
        assert XBET_PARTNER == 151
        assert f"partner={XBET_PARTNER}" in XBetScraper()._feed_url(1)

    def test_headers_carry_front_signature(self):
        headers = XBetScraper()._headers()
        assert headers["x-svc-source"] == "__V3_HOST_APP__"
        assert headers["x-requested-with"] == "XMLHttpRequest"
        assert "Referer" in headers


class TestMarketMap:
    def test_1x2_triplet(self):
        assert MARKET_MAP[(1, 1)] == ("1x2", 3, "home", None)
        assert MARKET_MAP[(1, 2)] == ("1x2", 3, "draw", None)
        assert MARKET_MAP[(1, 3)] == ("1x2", 3, "away", None)

    def test_totals_over_under(self):
        assert MARKET_MAP[(17, 9)][2] == "over"
        assert MARKET_MAP[(17, 10)][2] == "under"

    def test_team_totals_declare_scope(self):
        """G=15 = equipe domicile, G=62 = equipe exterieure (valide en live)."""
        assert MARKET_MAP[(15, 11)][3] == "home"
        assert MARKET_MAP[(62, 13)][3] == "away"

    def test_double_chance_group_is_excluded(self):
        """G=8 : issues qui se recouvrent (marge mesuree a 119 %)."""
        assert 8 in EXCLUDED_GROUPS
        assert not any(g == 8 for g, _ in MARKET_MAP)


class TestParsing:
    @pytest.mark.asyncio
    async def test_parses_expected_markets(self, scraper):
        odds = await scraper.scrape("football")
        # 3 (1x2) + 2 (total) + 2 (team home) + 2 (team away) + 2 (btts) = 11
        assert len(odds) == 11

    @pytest.mark.asyncio
    async def test_1x2_values(self, scraper):
        odds = await scraper.scrape("football")
        x2 = {o.selection: o.odds for o in odds if o.market_type == "1x2"}
        assert x2 == {"home": 2.025, "draw": 3.165, "away": 4.12}

    @pytest.mark.asyncio
    async def test_double_chance_is_never_emitted(self, scraper):
        odds = await scraper.scrape("football")
        assert all(o.odds not in (1.263, 1.387, 1.821) for o in odds)

    @pytest.mark.asyncio
    async def test_unknown_group_ignored(self, scraper):
        odds = await scraper.scrape("football")
        assert all(o.odds != 3.0 for o in odds)

    @pytest.mark.asyncio
    async def test_invalid_odds_rejected(self, scraper):
        odds = await scraper.scrape("football")
        assert all(o.odds > 1.0 for o in odds)

    @pytest.mark.asyncio
    async def test_team_totals_carry_scope_and_line(self, scraper):
        odds = await scraper.scrape("football")
        team = [o for o in odds if o.market_type == "goals_team"]
        assert {o.team_scope for o in team} == {"home", "away"}
        assert {o.line for o in team} == {1.5, 0.5}

    @pytest.mark.asyncio
    async def test_metadata(self, scraper):
        odds = await scraper.scrape("football")
        odd = odds[0]
        assert odd.bookmaker == "1xBet"
        assert odd.home_team == "CSKA Moscou"
        assert odd.away_team == "Baltika Kaliningrad"
        assert odd.competition == "Championnat de Russie"
        assert len({o.match_id for o in odds}) == 1

    @pytest.mark.asyncio
    async def test_margins_are_positive(self, scraper):
        """Coherence : un book ne propose jamais d'arbitrage sur lui-meme."""
        from surebet.arbitrage.detector import implied_margin

        odds = await scraper.scrape("football")
        x2 = [o.odds for o in odds if o.market_type == "1x2"]
        assert implied_margin(x2) > 1.0


class TestErrors:
    @pytest.mark.asyncio
    async def test_unsupported_sport(self):
        with pytest.raises(ValueError):
            await XBetScraper().scrape("tennis")

    @pytest.mark.asyncio
    async def test_unsuccessful_payload_raises(self, monkeypatch):
        s = XBetScraper()

        async def fake_fetch(url):
            return {"Success": False, "Error": "boom"}

        monkeypatch.setattr(s, "_fetch", fake_fetch)
        with pytest.raises(ScraperUnavailableError):
            await s.scrape("football")

    @pytest.mark.asyncio
    async def test_event_without_teams_skipped(self, monkeypatch):
        s = XBetScraper()

        async def fake_fetch(url):
            return {"Success": True, "Value": [{"O1": None, "O2": "B", "S": 1784912400, "E": []}]}

        monkeypatch.setattr(s, "_fetch", fake_fetch)
        assert await s.scrape("football") == []
