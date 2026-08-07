"""Normalisation des marches de basketball.

Le point structurant : au basket il n'y a PAS de nul, la prolongation
departage. Le vainqueur est donc un marche a deux issues, contrairement au
1X2 du football.

Le piege : certains bookmakers proposent AUSSI un marche « temps
reglementaire », ou le nul existe. Apparier les deux variantes donnerait un
faux surebet parfait — le calcul serait juste, mais une prolongation ferait
perdre les deux paris. Les tests verifient qu'elles ne peuvent pas se
rencontrer.
"""
from datetime import datetime, timedelta, timezone

import pytest

from surebet.arbitrage.detector import find_three_way, find_two_way
from surebet.normalizer.markets import normalize_market_label
from surebet.normalizer.schema import Odd, make_match_id

HOME, AWAY = "Real Madrid", "FC Barcelone"
START = datetime.now(timezone.utc) + timedelta(days=2)


def nm(marche, selection, sport="basketball"):
    return normalize_market_label(marche, selection, HOME, AWAY, sport)


def odd(bookmaker, market_type, selection, cote, n_outcomes=2):
    return Odd(
        bookmaker=bookmaker, sport="basketball", competition="Liga ACB",
        match_id=make_match_id(HOME, AWAY, START), home_team=HOME, away_team=AWAY,
        start_time=START, market_type=market_type, n_outcomes=n_outcomes,
        selection=selection, line=None, team_scope=None, odds=cote,
        url=f"https://{bookmaker}.test/e", scraped_at=datetime.now(timezone.utc),
    )


class TestVainqueurDeuxIssues:
    def test_vainqueur_est_un_marche_a_deux_issues(self):
        m = nm("Vainqueur du match", "1")
        assert m is not None
        assert m.market_type == "bb_moneyline"
        assert m.n_outcomes == 2
        assert m.selection == "home"

    def test_money_line_reconnu(self):
        for libelle in ("Money Line", "Moneyline", "Winner", "Gagnant du match"):
            m = nm(libelle, "2")
            assert m is not None, libelle
            assert m.n_outcomes == 2
            assert m.selection == "away"

    def test_resultat_du_match_vaut_deux_issues_au_basket(self):
        """Meme libelle qu'au football, mais deux issues : c'est le sport qui tranche."""
        m = nm("Resultat du match", "1")
        assert m.market_type == "bb_moneyline"
        assert m.n_outcomes == 2

    def test_le_meme_libelle_reste_a_trois_issues_au_football(self):
        """Non-regression : le chemin football ne doit pas bouger."""
        m = normalize_market_label("Resultat du match", "1", HOME, AWAY, "football")
        assert m.market_type == "1x2"
        assert m.n_outcomes == 3

    def test_sport_par_defaut_reste_le_football(self):
        """L'ancien appel a quatre arguments doit se comporter comme avant."""
        m = normalize_market_label("Resultat du match", "1", HOME, AWAY)
        assert m.market_type == "1x2"
        assert m.n_outcomes == 3

    def test_nul_refuse_hors_temps_reglementaire(self):
        """Un nul n'existe pas quand les prolongations comptent : on refuse."""
        assert nm("Vainqueur du match", "X") is None


class TestTempsReglementaire:
    def test_temps_reglementaire_garde_trois_issues(self):
        m = nm("Resultat du match (temps reglementaire)", "X")
        assert m is not None
        assert m.market_type == "bb_result_reg"
        assert m.n_outcomes == 3
        assert m.selection == "draw"

    def test_variantes_de_libelle_reconnues(self):
        for libelle in ("Vainqueur (sans prolongation)", "Winner regular time",
                        "Resultat hors prolongation"):
            m = nm(libelle, "1")
            assert m is not None, libelle
            assert m.market_type == "bb_result_reg", libelle
            assert m.n_outcomes == 3, libelle

    def test_les_deux_variantes_ont_des_marches_DIFFERENTS(self):
        """Le garde-fou essentiel : elles ne doivent jamais se rencontrer.

        Apparier « prolongations comprises » et « temps reglementaire »
        donnerait un faux surebet parfait.
        """
        avec_ot = nm("Vainqueur du match", "1")
        sans_ot = nm("Vainqueur du match (temps reglementaire)", "1")
        assert avec_ot.market_type != sans_ot.market_type


class TestDetectionBasket:
    def test_arbitrage_a_deux_issues_detecte(self):
        """1.95 / 2.15 -> S = 0.978, ROI ~2.3 %."""
        pool = [
            odd("1xBet",   "bb_moneyline", "home", 1.95),
            odd("Golcash", "bb_moneyline", "away", 2.15),
        ]
        opps = find_two_way(pool, min_roi=1.0, bankroll=10_000.0)
        assert len(opps) == 1
        assert opps[0].roi_pct == pytest.approx(2.30, abs=0.1)

    def test_pas_de_detection_avec_un_seul_bookmaker(self):
        pool = [
            odd("1xBet", "bb_moneyline", "home", 1.95),
            odd("1xBet", "bb_moneyline", "away", 2.15),
        ]
        assert find_two_way(pool, min_roi=1.0) == []

    def test_les_deux_variantes_ne_se_melangent_pas(self):
        """Cotes tres attractives, mais marches differents : aucune detection.

        Sans la separation, ces quatre cotes formeraient un « arbitrage »
        qu'une prolongation transformerait en double perte.
        """
        pool = [
            odd("1xBet",   "bb_moneyline",  "home", 2.10),
            odd("Golcash", "bb_result_reg", "away", 2.10, n_outcomes=3),
            odd("Golcash", "bb_result_reg", "draw", 15.0, n_outcomes=3),
        ]
        assert find_two_way(pool, min_roi=0.1) == []
        assert find_three_way(pool, min_roi=0.1) == []

    def test_points_total_fonctionne_deja(self):
        """Les marches over/under du basket passaient deja : non-regression."""
        m = nm("Total de points", "Plus de 180.5")
        assert m is not None
        assert m.market_type == "points_total"
        assert m.n_outcomes == 2
        assert m.selection == "over"
        assert m.line == 180.5
