"""Tests de la reconciliation floue des matchs entre bookmakers."""
from datetime import datetime, timedelta, timezone

from surebet.arbitrage.reconcile import reconcile_pool, reconciliation_report
from surebet.normalizer.schema import Odd, make_match_id

DAY = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)


def odd(bk, home, away, sel="home", price=2.0, mtype="1x2", n=3, start=DAY):
    return Odd(
        bookmaker=bk, sport="football", competition="X",
        match_id=make_match_id(home, away, start), home_team=home, away_team=away,
        start_time=start, market_type=mtype, n_outcomes=n, selection=sel,
        line=None, team_scope=None, odds=price, url="https://x/e",
        scraped_at=datetime.now(timezone.utc),
    )


class TestReconcilePool:
    def test_merges_slightly_different_team_names(self):
        """"FC Arges" et "Arges" -> meme match apres reconciliation."""
        pool = [
            odd("1xBet", "FC Arges", "FC Petrolul Ploiesti", "home"),
            odd("Paryaj Lakay", "Arges", "Petrolul Ploiesti", "away"),
        ]
        assert len({o.match_id for o in pool}) == 2  # avant : distincts
        reconciled = reconcile_pool(pool)
        assert len({o.match_id for o in reconciled}) == 1  # apres : fusionnes

    def test_distinct_matches_stay_separate(self):
        pool = [
            odd("1xBet", "Real Madrid", "Barcelona"),
            odd("Golcash", "Bayern", "Dortmund"),
        ]
        assert len({o.match_id for o in reconcile_pool(pool)}) == 2

    def test_u23_never_merged_with_senior(self):
        """Le garde-fou de niveau d'equipe reste actif apres reconciliation."""
        pool = [
            odd("1xBet", "Eltham Redbacks", "Melbourne Serbia"),
            odd("Paryaj Lakay", "Eltham Redbacks U-23", "Melbourne Serbia U-23"),
        ]
        assert len({o.match_id for o in reconcile_pool(pool)}) == 2

    def test_different_days_not_merged(self):
        pool = [
            odd("1xBet", "FC Arges", "Petrolul", start=DAY),
            odd("Golcash", "FC Arges", "Petrolul", start=DAY + timedelta(days=1)),
        ]
        assert len({o.match_id for o in reconcile_pool(pool)}) == 2

    def test_swapped_orientation_not_merged(self):
        """Domicile/exterieur inverses -> non fusionne (eviterait un faux arb)."""
        pool = [
            odd("1xBet", "Real Madrid", "Barcelona"),
            odd("Golcash", "Barcelona", "Real Madrid"),
        ]
        assert len({o.match_id for o in reconcile_pool(pool)}) == 2

    def test_reconciliation_enables_cross_book_detection(self):
        """Apres fusion, un surebet cross-book devient detectable."""
        from surebet.ai.scout import Scout

        # meme match, noms differents, cotes 1X2 de l'exemple §5.5 sur 3 books
        pool = [
            odd("Paryaj Lakay", "FC Arges", "Petrolul Ploiesti", "home", 3.55),
            odd("1xBet", "Arges", "Petrolul Ploiesti", "draw", 3.90),
            odd("Golcash", "F.C. Arges", "Petrolul Ploiesti", "away", 3.30),
        ]
        # sans reconciliation : 3 match_id distincts, aucun surebet
        assert len({o.match_id for o in pool}) == 3
        opps = Scout(min_roi=1.0, bankroll=50_000.0).evaluate(pool)
        assert len(opps) == 1
        assert opps[0].roi_pct > 18  # ROI de l'exemple §5.5

    def test_preserves_odds_data(self):
        pool = [odd("1xBet", "FC Arges", "Petrolul", "home", 2.5)]
        reconciled = reconcile_pool(pool)
        assert reconciled[0].odds == 2.5
        assert reconciled[0].bookmaker == "1xBet"


class TestReconciliationReport:
    def test_counts_merges(self):
        pool = [
            odd("1xBet", "FC Arges", "Petrolul"),
            odd("Paryaj Lakay", "Arges", "Petrolul"),
            odd("Golcash", "Bayern", "Dortmund"),
        ]
        report = reconciliation_report(pool)
        assert report["match_ids_before"] == 3
        assert report["match_ids_after"] == 2
        assert report["merged"] == 1
        assert report["cross_book_matches"] == 1
