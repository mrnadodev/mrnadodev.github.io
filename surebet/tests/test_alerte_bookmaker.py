"""Filtre d'alerte par bookmaker.

Depuis aout 2026, l'API de Paryaj Lakay refuse l'adresse du VPS (403) alors
qu'elle repond depuis une connexion haitienne. Deux machines se partagent donc
la couverture. Sans filtre, celle d'Haiti reenverrait toutes les occasions que
le VPS a deja signalees et l'abonne recevrait chaque surebet en double.

Les tests verifient les deux sens : ce qui passe, et surtout ce qui est retenu.
"""
from datetime import datetime, timedelta, timezone

from surebet.notifier.telegram import should_alert
from surebet.normalizer.schema import Leg, Opportunity

START = datetime.now(timezone.utc) + timedelta(days=1)


def _jambe(bookmaker, selection):
    return Leg(
        bookmaker=bookmaker, selection=selection, odds=2.1, stake=5000.0,
        url=f"https://{bookmaker.lower().replace(' ', '')}.test/e",
        event_label=f"Lyon - Nice / {selection}",
    )


def _occasion(books, roi=5.0, score=88):
    legs = [_jambe(b, s) for b, s in zip(books, ("home", "away", "draw"))]
    return Opportunity(
        match_id="m1", sport="football", match_label="Lyon - Nice", match_date=START,
        market_type="1x2", line=None, team_scope=None, n_outcomes=len(legs),
        legs=legs, roi_pct=roi, score_ia=score,
    )


class TestSansFiltre:
    def test_comportement_d_origine_inchange(self):
        """Filtre vide : rien ne change pour le VPS, qui alerte sur tout."""
        opp = _occasion(["Paryaj Pam", "Golcash"])
        assert should_alert(opp, 3.0, 70) is True
        assert should_alert(opp, 3.0, 70, None) is True
        assert should_alert(opp, 3.0, 70, "") is True


class TestAvecFiltre:
    def test_occasion_contenant_le_bookmaker_passe(self):
        opp = _occasion(["Paryaj Lakay", "Golcash"])
        assert should_alert(opp, 3.0, 70, "Paryaj Lakay") is True

    def test_occasion_sans_le_bookmaker_est_retenue(self):
        """Le cas qui evite les doublons : le VPS a deja signale celle-ci."""
        opp = _occasion(["Paryaj Pam", "Golcash"])
        assert should_alert(opp, 3.0, 70, "Paryaj Lakay") is False

    def test_le_bookmaker_en_troisieme_jambe_compte(self):
        opp = _occasion(["Paryaj Pam", "Golcash", "Paryaj Lakay"])
        assert should_alert(opp, 3.0, 70, "Paryaj Lakay") is True

    def test_casse_et_espaces_ignores(self):
        """La valeur vient d'une variable d'environnement, saisie a la main."""
        opp = _occasion(["Paryaj Lakay", "Golcash"])
        for saisie in ("paryaj lakay", "  Paryaj Lakay  ", "PARYAJ LAKAY"):
            assert should_alert(opp, 3.0, 70, saisie) is True, saisie


class TestLesSeuilsRestentPrioritaires:
    def test_roi_insuffisant_refuse_meme_avec_le_bon_bookmaker(self):
        """Le filtre ajoute une condition, il n'en relache aucune."""
        opp = _occasion(["Paryaj Lakay", "Golcash"], roi=1.2)
        assert should_alert(opp, 3.0, 70, "Paryaj Lakay") is False

    def test_score_insuffisant_refuse_aussi(self):
        opp = _occasion(["Paryaj Lakay", "Golcash"], score=40)
        assert should_alert(opp, 3.0, 70, "Paryaj Lakay") is False
