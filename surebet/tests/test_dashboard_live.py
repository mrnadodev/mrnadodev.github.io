"""Tests de la vue live du dashboard (libelles + classement cross-book)."""
from datetime import datetime, timezone

import pytest

from surebet.dashboard.live import (
    market_label,
    outcome_label,
    rank_cross_book,
    scan_stats,
)
from surebet.normalizer.schema import Odd, make_match_id

START = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)


def odd(bk, sel, price, mtype="1x2", n=3, line=None, scope=None,
        home="Real Madrid", away="FC Barcelone"):
    return Odd(
        bookmaker=bk, sport="football", competition="Champions League",
        match_id=make_match_id(home, away, START), home_team=home, away_team=away,
        start_time=START, market_type=mtype, n_outcomes=n, selection=sel,
        line=line, team_scope=scope, odds=price, url=f"https://{bk}.test/e",
        scraped_at=datetime.now(timezone.utc),
    )


class TestOutcomeLabel:
    def test_1x2_labels(self):
        assert outcome_label("home", None, None) == "Victoire Domicile (1)"
        assert outcome_label("draw", None, None) == "Nul (X)"
        assert outcome_label("away", None, None) == "Victoire Extérieur (2)"

    def test_over_under_with_line(self):
        assert outcome_label("over", 2.5, None) == "Plus de 2.5"
        assert outcome_label("under", 2.5, None) == "Moins de 2.5"

    def test_team_scoped_over(self):
        assert outcome_label("over", 1.5, "home") == "Plus de 1.5 dom."
        assert outcome_label("under", 1.5, "away") == "Moins de 1.5 ext."


class TestMarketLabel:
    def test_known_markets(self):
        assert market_label("1x2") == "3-Way (1X2)"
        assert market_label("btts") == "Les deux marquent"

    def test_total_carries_line(self):
        assert market_label("goals_total", 2.5) == "Total buts 2.5"


class TestRankCrossBook:
    def test_detects_true_surebet_with_stakes(self):
        """3 books, cotes de l'exemple §5.5 -> surebet avec mises calculees."""
        pool = [
            odd("Paryaj Lakay", "home", 3.55),
            odd("1xBet", "draw", 3.90),
            odd("Golcash", "away", 3.30),
        ]
        ranked = rank_cross_book(pool, bankroll=50_000.0)
        assert len(ranked) == 1
        opp = ranked[0]
        assert opp.is_surebet is True
        assert opp.margin == pytest.approx(0.84113, abs=1e-5)
        assert opp.roi_pct == pytest.approx(18.8876, abs=0.01)
        assert opp.n_issues == 3
        # mises reparties uniquement pour un vrai surebet
        assert sum(l.stake for l in opp.legs) == pytest.approx(50_000.0, abs=1.0)
        assert {l.bookmaker for l in opp.legs} == {"Paryaj Lakay", "1xBet", "Golcash"}

    def test_near_miss_has_no_stakes_but_shows_odds(self):
        """Combinaison M>1 : pas de mises, mais les cotes par issue sont exposees."""
        pool = [
            odd("Golcash", "home", 2.0),
            odd("Paryaj Pam", "draw", 3.0),
            odd("Golcash", "away", 3.0),
            odd("Paryaj Pam", "home", 1.9),
        ]
        ranked = rank_cross_book(pool)
        assert len(ranked) == 1
        opp = ranked[0]
        assert opp.is_surebet is False
        assert all(l.stake == 0.0 for l in opp.legs)
        assert len(opp.legs) == 3  # cotes visibles pour chaque issue
        assert all(l.odds > 1.0 for l in opp.legs)

    def test_single_bookmaker_group_is_excluded(self):
        """Un seul book sur toutes les issues -> pas une opportunite cross-book."""
        pool = [
            odd("Golcash", "home", 3.55),
            odd("Golcash", "draw", 3.90),
            odd("Golcash", "away", 3.30),
        ]
        assert rank_cross_book(pool) == []

    def test_results_sorted_by_margin(self):
        pool = [
            # marche tendu (surebet)
            odd("A", "home", 3.55), odd("B", "draw", 3.90), odd("C", "away", 3.30),
            # marche large, autre match
            odd("A", "over", 1.5, "goals_total", 2, 2.5, None, "X", "Y"),
            odd("B", "under", 1.5, "goals_total", 2, 2.5, None, "X", "Y"),
        ]
        ranked = rank_cross_book(pool)
        assert len(ranked) == 2
        assert ranked[0].margin <= ranked[1].margin

    def test_outcome_labels_populated(self):
        pool = [odd("Golcash", "home", 3.0), odd("Beltifish", "draw", 3.89),
                odd("Paryaj Pam", "away", 4.57)]
        opp = rank_cross_book(pool)[0]
        outcomes = {l.selection: l.outcome for l in opp.legs}
        assert outcomes["home"] == "Victoire Domicile (1)"
        assert outcomes["away"] == "Victoire Extérieur (2)"


class TestScanStats:
    def test_counts_matches_and_bookmakers(self):
        pool = [
            odd("Golcash", "home", 3.0), odd("1xBet", "draw", 3.5),
            odd("Golcash", "over", 1.9, "goals_total", 2, 2.5, None, "A", "B"),
        ]
        opps = rank_cross_book(pool)
        stats = scan_stats(pool, opps)
        assert stats["matches_analysed"] == 2
        assert stats["bookmakers_count"] == 2
        assert set(stats["bookmakers"]) == {"Golcash", "1xBet"}

    def test_empty_pool(self):
        stats = scan_stats([], [])
        assert stats["matches_analysed"] == 0
        assert stats["surebets"] == 0
