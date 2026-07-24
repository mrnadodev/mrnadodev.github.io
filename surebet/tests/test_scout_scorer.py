"""Tests de la couche IA scout + scorer (spec MISSION §6.2, §6.3)."""
from datetime import datetime, timedelta, timezone

import pytest

from surebet.ai.scorer import ScoringContext, score_opportunity
from surebet.ai.scout import Scout
from surebet.normalizer.schema import Odd


def _odd(bookmaker, selection, odds, market="1x2", line=None, n=3, home="Ghana", away="Colombie"):
    return Odd(
        bookmaker=bookmaker,
        sport="football",
        competition="Amical",
        match_id="m1",
        home_team=home,
        away_team=away,
        start_time=datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc),
        market_type=market,
        n_outcomes=n,
        selection=selection,
        line=line,
        team_scope=None,
        odds=odds,
        url=f"https://{bookmaker}.example/bet",
        scraped_at=datetime.now(timezone.utc),
    )


class TestScoutDetection:
    def test_three_way_surebet_detected_and_staked(self):
        # §5.5 : 3.55 / 3.90 / 3.30 sur 3 bookmakers -> M=0.841, ROI 18.9%
        pool = [
            _odd("Paryaj Lakay", "home", 3.55),
            _odd("1xBet", "draw", 3.90),
            _odd("Golcash", "away", 3.30),
        ]
        scout = Scout(min_roi=1.0, bankroll=50_000.0)
        opps = scout.evaluate(pool)
        assert len(opps) == 1
        opp = opps[0]
        assert opp.roi_pct == pytest.approx(18.89, abs=0.1)
        # mises assignees et arrondies, somme = bankroll
        assert sum(leg.stake for leg in opp.legs) == pytest.approx(50_000.0, abs=1.0)

    def test_two_way_surebet_detected(self):
        pool = [
            _odd("Paryaj Pam", "under", 2.16, market="shots_team", line=7.5, n=2),
            _odd("Golcash", "over", 2.00, market="shots_team", line=7.5, n=2),
        ]
        scout = Scout(min_roi=1.0, bankroll=50_000.0)
        opps = scout.evaluate(pool)
        assert len(opps) == 1
        assert opps[0].roi_pct == pytest.approx(3.85, abs=0.05)

    def test_no_surebet_when_margin_above_one(self):
        pool = [
            _odd("A", "home", 1.80),
            _odd("B", "draw", 3.30),
            _odd("C", "away", 3.40),
        ]
        scout = Scout(min_roi=1.0)
        assert scout.evaluate(pool) == []

    def test_quasi_surebet_tracking_and_trajectory(self):
        scout = Scout(bankroll=50_000.0)
        # M = 1/2.02 + 1/2.02 = 0.990 -> quasi-surebet limite basse
        pool_1 = [
            _odd("A", "under", 2.00, market="corners_total", line=9.5, n=2),
            _odd("B", "over", 2.00, market="corners_total", line=9.5, n=2),
        ]
        first = scout.detect_quasi_surebets(pool_1)
        assert len(first) == 1
        # les cotes s'ameliorent -> M diminue mais reste dans la bande quasi
        pool_2 = [
            _odd("A", "under", 2.01, market="corners_total", line=9.5, n=2),
            _odd("B", "over", 2.01, market="corners_total", line=9.5, n=2),
        ]
        second = scout.detect_quasi_surebets(pool_2)
        assert second[0].is_improving is True

    def test_hot_markets_prioritization(self):
        scout = Scout(bankroll=50_000.0)
        scout.evaluate([
            _odd("Paryaj Lakay", "home", 3.55),
            _odd("1xBet", "draw", 3.90),
            _odd("Golcash", "away", 3.30),
        ])
        assert scout.hot_markets(1) == [("1x2", 1)]
        priority = scout.scrape_priority()
        assert set(priority.keys()) == {"Paryaj Lakay", "1xBet", "Golcash"}
        assert sum(priority.values()) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_scout_template_explanation_without_llm():
    scout = Scout(bankroll=50_000.0)
    opps = scout.evaluate([
        _odd("Paryaj Lakay", "home", 3.55),
        _odd("1xBet", "draw", 3.90),
        _odd("Golcash", "away", 3.30),
    ])
    text = await scout.explain(opps[0])
    assert "Surebet" in text
    assert "Paryaj Lakay" in text and "1xBet" in text and "Golcash" in text


class TestScorer:
    def _fresh_opportunity(self):
        scout = Scout(bankroll=50_000.0)
        return scout.evaluate([
            _odd("Paryaj Lakay", "home", 3.55),
            _odd("1xBet", "draw", 3.90),
            _odd("Golcash", "away", 3.30),
        ])[0]

    def test_fresh_plausible_opportunity_scores_high(self):
        opp = self._fresh_opportunity()
        score = score_opportunity(opp)
        assert score >= 70

    def test_stale_opportunity_penalized(self):
        opp = self._fresh_opportunity()
        opp.detected_at = datetime.now(timezone.utc) - timedelta(seconds=180)
        assert score_opportunity(opp) < 70

    def test_red_flag_implausible_roi_on_major_market(self):
        # ROI > 25% sur 1x2 -> plausibilite 0, score effondre
        scout = Scout(bankroll=50_000.0)
        opp = scout.evaluate([
            _odd("A", "home", 5.0),
            _odd("B", "draw", 5.0),
            _odd("C", "away", 5.0),
        ])[0]
        assert opp.roi_pct > 25.0
        assert score_opportunity(opp) < 70

    def test_low_matching_confidence_lowers_score(self):
        opp = self._fresh_opportunity()
        high = score_opportunity(opp, ScoringContext(match_confidences=[0.95, 0.95, 0.95]))
        low = score_opportunity(opp, ScoringContext(match_confidences=[0.5, 0.5, 0.5]))
        assert low < high
