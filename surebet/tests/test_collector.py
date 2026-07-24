"""Tests du service de collecte (pool partage, sante, isolation des pannes).

Aucun navigateur ni reseau : les scrapers sont des doubles de test. On valide
le contrat du collector, pas Playwright.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from surebet.collector.pool import OddsPool
from surebet.collector.service import BookmakerHealth, Collector, CollectorTask
from surebet.normalizer.schema import Odd, make_match_id
from surebet.scrapers.base import ScraperUnavailableError

START = datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc)


def make_odd(bookmaker: str, selection: str, odds: float, scraped_at: datetime | None = None) -> Odd:
    return Odd(
        bookmaker=bookmaker, sport="football", competition="Test",
        match_id=make_match_id("A", "B", START), home_team="A", away_team="B",
        start_time=START, market_type="1x2", n_outcomes=3, selection=selection,
        line=None, team_scope=None, odds=odds, url="https://x.test/e",
        scraped_at=scraped_at or datetime.now(timezone.utc),
    )


class FakeScraper:
    def __init__(self, name: str, odds: list[Odd] | None = None, fail_with: Exception | None = None):
        self.bookmaker_name = name
        self._odds = odds or []
        self.fail_with = fail_with
        self.calls = 0

    async def scrape(self, sport: str) -> list[Odd]:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return self._odds


class TestOddsPool:
    @pytest.mark.asyncio
    async def test_update_and_snapshot_merges_bookmakers(self):
        pool = OddsPool()
        await pool.update("A", [make_odd("A", "home", 2.0)])
        await pool.update("B", [make_odd("B", "away", 3.0)])
        snap = await pool.snapshot()
        assert len(snap) == 2
        assert {o.bookmaker for o in snap} == {"A", "B"}

    @pytest.mark.asyncio
    async def test_update_replaces_previous_contribution(self):
        """Une cote retiree par le bookmaker disparait au cycle suivant."""
        pool = OddsPool()
        await pool.update("A", [make_odd("A", "home", 2.0), make_odd("A", "draw", 3.0)])
        await pool.update("A", [make_odd("A", "home", 2.1)])
        snap = await pool.snapshot()
        assert len(snap) == 1
        assert snap[0].odds == 2.1

    @pytest.mark.asyncio
    async def test_stale_odds_excluded_from_snapshot(self):
        """Cotes de plus de max_age_s ecartees (spec MISSION §9)."""
        pool = OddsPool(max_age_s=60)
        old = make_odd("A", "home", 2.0, scraped_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        fresh = make_odd("B", "away", 3.0)
        await pool.update("A", [old])
        await pool.update("B", [fresh])
        snap = await pool.snapshot()
        assert len(snap) == 1
        assert snap[0].bookmaker == "B"
        assert len(await pool.snapshot(include_stale=True)) == 2

    @pytest.mark.asyncio
    async def test_stats_reports_fresh_counts(self):
        pool = OddsPool(max_age_s=60)
        old = make_odd("A", "home", 2.0, scraped_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        await pool.update("A", [old, make_odd("A", "draw", 3.0)])
        stats = await pool.stats()
        assert len(stats) == 1
        assert stats[0].count == 2
        assert stats[0].fresh_count == 1
        assert stats[0].age_seconds is not None

    @pytest.mark.asyncio
    async def test_clear_removes_bookmaker(self):
        pool = OddsPool()
        await pool.update("A", [make_odd("A", "home", 2.0)])
        await pool.clear("A")
        assert await pool.snapshot() == []

    @pytest.mark.asyncio
    async def test_concurrent_updates_are_safe(self):
        pool = OddsPool()
        async def writer(name: str):
            for _ in range(20):
                await pool.update(name, [make_odd(name, "home", 2.0)])
        await asyncio.gather(writer("A"), writer("B"), writer("C"))
        snap = await pool.snapshot()
        assert len(snap) == 3


class TestCollectorCollectOnce:
    @pytest.mark.asyncio
    async def test_successful_cycle_fills_pool_and_health(self):
        pool = OddsPool()
        scraper = FakeScraper("A", [make_odd("A", "home", 2.0)])
        task = CollectorTask(scraper=scraper, interval_s=1)
        collector = Collector(pool, [task])

        n = await collector.collect_once(task)
        assert n == 1
        assert len(await pool.snapshot()) == 1
        assert task.health.is_healthy
        assert task.health.last_success is not None
        assert task.health.total_odds == 1

    @pytest.mark.asyncio
    async def test_scraper_failure_is_isolated_and_recorded(self):
        pool = OddsPool()
        bad = CollectorTask(FakeScraper("bad", fail_with=ScraperUnavailableError("down")), interval_s=1)
        good = CollectorTask(FakeScraper("good", [make_odd("good", "home", 2.0)]), interval_s=1)
        collector = Collector(pool, [bad, good])

        assert await collector.collect_once(bad) == 0
        assert await collector.collect_once(good) == 1

        # la panne d'un book n'empeche pas l'autre de publier
        assert [o.bookmaker for o in await pool.snapshot()] == ["good"]
        assert bad.health.consecutive_failures == 1
        assert not bad.health.is_healthy
        assert good.health.is_healthy

    @pytest.mark.asyncio
    async def test_unexpected_exception_does_not_propagate(self):
        pool = OddsPool()
        task = CollectorTask(FakeScraper("boom", fail_with=RuntimeError("kaboom")), interval_s=1)
        collector = Collector(pool, [task])
        assert await collector.collect_once(task) == 0
        assert task.health.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_recovery_resets_failure_counter(self):
        pool = OddsPool()
        scraper = FakeScraper("flaky", fail_with=ScraperUnavailableError("down"))
        task = CollectorTask(scraper, interval_s=1)
        collector = Collector(pool, [task])

        await collector.collect_once(task)
        assert task.health.consecutive_failures == 1

        scraper.fail_with = None
        scraper._odds = [make_odd("flaky", "home", 2.0)]
        await collector.collect_once(task)
        assert task.health.consecutive_failures == 0
        assert task.health.is_healthy


class TestUnavailabilityAlert:
    @pytest.mark.asyncio
    async def test_alert_fires_after_threshold(self):
        """Indisponibilite > seuil -> alerte (spec MISSION §9)."""
        pool = OddsPool()
        task = CollectorTask(FakeScraper("A", fail_with=ScraperUnavailableError("down")), interval_s=1)
        alerted: list[BookmakerHealth] = []

        async def on_unavailable(h): alerted.append(h)

        collector = Collector(pool, [task], unavailable_alert_after_s=300, on_unavailable=on_unavailable)
        # succes ancien puis pannes : depasse le seuil
        task.health.last_success = datetime.now(timezone.utc) - timedelta(seconds=600)
        await collector.collect_once(task)

        assert len(alerted) == 1
        assert alerted[0].bookmaker == "A"

    @pytest.mark.asyncio
    async def test_alert_not_repeated_while_still_down(self):
        pool = OddsPool()
        task = CollectorTask(FakeScraper("A", fail_with=ScraperUnavailableError("down")), interval_s=1)
        alerted = []

        async def on_unavailable(h): alerted.append(h)

        collector = Collector(pool, [task], unavailable_alert_after_s=300, on_unavailable=on_unavailable)
        task.health.last_success = datetime.now(timezone.utc) - timedelta(seconds=600)
        await collector.collect_once(task)
        await collector.collect_once(task)
        assert len(alerted) == 1  # pas de spam d'alertes

    @pytest.mark.asyncio
    async def test_no_alert_before_threshold(self):
        pool = OddsPool()
        task = CollectorTask(FakeScraper("A", fail_with=ScraperUnavailableError("down")), interval_s=1)
        alerted = []

        async def on_unavailable(h): alerted.append(h)

        collector = Collector(pool, [task], unavailable_alert_after_s=300, on_unavailable=on_unavailable)
        task.health.last_success = datetime.now(timezone.utc) - timedelta(seconds=10)
        await collector.collect_once(task)
        assert alerted == []

    @pytest.mark.asyncio
    async def test_alert_when_never_succeeded_after_three_failures(self):
        pool = OddsPool()
        task = CollectorTask(FakeScraper("A", fail_with=ScraperUnavailableError("down")), interval_s=1)
        alerted = []

        async def on_unavailable(h): alerted.append(h)

        collector = Collector(pool, [task], on_unavailable=on_unavailable)
        for _ in range(3):
            await collector.collect_once(task)
        assert len(alerted) == 1


class TestCollectorLoop:
    @pytest.mark.asyncio
    async def test_start_stop_runs_multiple_cycles(self):
        pool = OddsPool()
        scraper = FakeScraper("A", [make_odd("A", "home", 2.0)])
        task = CollectorTask(scraper, interval_s=0.05)
        collector = Collector(pool, [task])

        await collector.start()
        await asyncio.sleep(0.25)
        await collector.stop()

        assert scraper.calls >= 2
        assert task.health.total_cycles >= 2

    @pytest.mark.asyncio
    async def test_independent_intervals_per_bookmaker(self):
        """Un book live (cadence rapide) est scrape plus souvent qu'un pre-match."""
        pool = OddsPool()
        fast = FakeScraper("fast", [make_odd("fast", "home", 2.0)])
        slow = FakeScraper("slow", [make_odd("slow", "away", 3.0)])
        tasks = [CollectorTask(fast, interval_s=0.05), CollectorTask(slow, interval_s=0.5)]
        collector = Collector(pool, tasks)

        await collector.start()
        await asyncio.sleep(0.3)
        await collector.stop()

        assert fast.calls > slow.calls

    @pytest.mark.asyncio
    async def test_failing_bookmaker_does_not_stop_the_loop(self):
        pool = OddsPool()
        bad = FakeScraper("bad", fail_with=ScraperUnavailableError("down"))
        good = FakeScraper("good", [make_odd("good", "home", 2.0)])
        collector = Collector(pool, [CollectorTask(bad, 0.05), CollectorTask(good, 0.05)])

        await collector.start()
        await asyncio.sleep(0.25)
        await collector.stop()

        assert bad.calls >= 2  # continue d'essayer
        assert good.calls >= 2
        assert len(await pool.snapshot()) == 1


class TestSessionInjection:
    """La session persistante injectee doit remplacer le navigateur ephemere."""

    @pytest.mark.asyncio
    async def test_scraper_uses_injected_session_instead_of_launching_browser(self):
        from surebet.scrapers.paryajlakay import ParyajLakayScraper

        class FakeSession:
            def __init__(self):
                self.renders = []

            async def render(self, url, wait_selector=None, timeout_ms=None):
                self.renders.append(url)
                return "<div class='page-content'></div>"

        scraper = ParyajLakayScraper()
        session = FakeSession()
        scraper.attach_session(session)

        html = await scraper._render_html("https://x.test/event", ".page-content")
        assert html == "<div class='page-content'></div>"
        assert session.renders == ["https://x.test/event"]
        # succes enregistre sans avoir lance de navigateur
        assert scraper.last_success_at is not None

    def test_scraper_without_session_defaults_to_none(self):
        from surebet.scrapers.paryajlakay import ParyajLakayScraper

        assert ParyajLakayScraper().session is None


class TestCollectorFeedsArbitrage:
    @pytest.mark.asyncio
    async def test_pool_snapshot_feeds_scout_and_detects_surebet(self):
        """Bout-en-bout : deux books publient dans le pool -> surebet detecte."""
        from surebet.ai.scout import Scout

        pool = OddsPool()
        # 1X2 reparti sur 3 books, cotes de l'exemple de reference §5.5
        a = FakeScraper("Paryaj Lakay", [make_odd("Paryaj Lakay", "home", 3.55)])
        b = FakeScraper("1xBet", [make_odd("1xBet", "draw", 3.90)])
        c = FakeScraper("Golcash", [make_odd("Golcash", "away", 3.30)])
        collector = Collector(pool, [CollectorTask(s, 1) for s in (a, b, c)])

        for t in collector.tasks:
            await collector.collect_once(t)

        snapshot = await pool.snapshot()
        assert len(snapshot) == 3

        opportunities = Scout(min_roi=1.0, bankroll=50_000.0).evaluate(snapshot)
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp.n_outcomes == 3
        assert opp.margin == pytest.approx(0.84113, abs=1e-5)
        assert opp.roi_pct == pytest.approx(18.8876, abs=0.01)
