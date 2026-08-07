"""Tests de la collecte d'URLs d'evenements chez Paryaj Lakay.

Paryaj Lakay est le book pivot (cotation independante), donc sa couverture
conditionne le nombre d'arbitrages detectables. La page listing n'expose qu'une
poignee de matchs vedettes ; les competitions du menu ne sont pas des liens
<a> mais des elements cliquables, d'ou la recolte par clics.
"""
import pytest

from surebet.scrapers.paryajlakay import ParyajLakayScraper

LISTING_HTML = """
<div>
  <a href="/sports/event/cska-moscou-fc-baltika-kaliningrad-m80263922">CSKA</a>
  <a href="/sports/event/viborg-ff-odense-boldklub-m79088855">Viborg</a>
  <a href="/sports/event/uta-arad-asc-otelul-galati-m79197883">UTA</a>
  <a href="/instant-games/llc/Aviator">pas un match</a>
  <a href="/sports/101/24020/24212">competition, pas un match</a>
</div>
"""


class TestUrlsFromHtml:
    def setup_method(self):
        self.scraper = ParyajLakayScraper()

    def test_extracts_only_event_urls(self):
        urls = self.scraper._urls_from_html(LISTING_HTML)
        assert len(urls) == 3
        assert all("/sports/event/" in u for u in urls)

    def test_urls_are_absolute(self):
        urls = self.scraper._urls_from_html(LISTING_HTML)
        assert all(u.startswith("https://www.paryajlakay.com/sports/event/") for u in urls)

    def test_ignores_non_event_links(self):
        urls = self.scraper._urls_from_html(LISTING_HTML)
        assert not any("Aviator" in u for u in urls)
        assert not any("/sports/101/" in u for u in urls)

    def test_deduplicates(self):
        html = LISTING_HTML + LISTING_HTML
        assert len(self.scraper._urls_from_html(html)) == 3

    def test_empty_html_yields_nothing(self):
        assert self.scraper._urls_from_html("<div></div>") == set()


class TestListEventUrls:
    @pytest.mark.asyncio
    async def test_without_session_falls_back_to_listing_only(self):
        """Sans navigateur pilotable, la recolte par clics est sautee proprement."""
        scraper = ParyajLakayScraper()

        async def fake_render(url, wait_selector=None, timeout_ms=20000):
            return LISTING_HTML

        scraper._render_html = fake_render
        urls = await scraper._list_event_urls("football")
        assert len(urls) == 3
        assert scraper.session is None

    @pytest.mark.asyncio
    async def test_click_harvest_adds_events_from_competitions(self):
        """La recolte par clics doit s'ajouter aux matchs vedettes."""
        scraper = ParyajLakayScraper()

        extra = '<a href="/sports/event/amiens-sc-us-boulogne-m81814135">Amiens</a>'

        class FakePage:
            def __init__(self):
                self.calls = 0

            async def evaluate(self, script, arg=None):
                # 1er appel : deploiement du sport ; 2e : liste des competitions
                self.calls += 1
                if "filter" in script and "map" in script:
                    return ["D1 Russie"]
                return None

            async def content(self):
                return LISTING_HTML + extra

            async def wait_for_timeout(self, ms):
                return None

        class FakeSession:
            page = FakePage()

        scraper.session = FakeSession()

        async def fake_render(url, wait_selector=None, timeout_ms=20000):
            return LISTING_HTML

        scraper._render_html = fake_render
        urls = await scraper._list_event_urls("football")
        assert len(urls) == 4
        assert any("amiens" in u for u in urls)

    @pytest.mark.asyncio
    async def test_limit_is_respected(self):
        scraper = ParyajLakayScraper()

        async def fake_render(url, wait_selector=None, timeout_ms=20000):
            return LISTING_HTML

        scraper._render_html = fake_render
        assert len(await scraper._list_event_urls("football", limit=2)) == 2

    @pytest.mark.asyncio
    async def test_click_harvest_failure_does_not_break_listing(self):
        """Une erreur pendant les clics ne doit pas perdre les matchs deja trouves."""
        scraper = ParyajLakayScraper()

        class ExplodingPage:
            async def evaluate(self, script, arg=None):
                raise RuntimeError("DOM indisponible")

            async def content(self):
                return ""

            async def wait_for_timeout(self, ms):
                return None

        class FakeSession:
            page = ExplodingPage()

        scraper.session = FakeSession()

        async def fake_render(url, wait_selector=None, timeout_ms=20000):
            return LISTING_HTML

        scraper._render_html = fake_render
        urls = await scraper._list_event_urls("football")
        assert len(urls) == 3  # les matchs vedettes restent collectes
