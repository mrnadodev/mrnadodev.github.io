"""Duree de vie bornee d'une session navigateur.

Le 12 aout 2026, un portable de 8 Go a gele apres 4 heures de collecte. Le
meme symptome avait ete impute au ballooning de l'hebergeur du VPS ; une
machine personnelle, sans hyperviseur, l'a reproduit. La fuite est reelle et
elle est dans Chromium, pas dans notre code.

On ne corrige pas cette fuite, on la borne. Ces tests verifient la decision
de recyclage — la seule partie que l'on puisse eprouver sans lancer un vrai
navigateur.
"""
from datetime import datetime, timedelta, timezone

import pytest

from surebet.collector.session import BrowserSession


def session(nav=0, minutes=0, age_min=None, navigations=0):
    s = BrowserSession(name="Test", max_navigations=nav, max_minutes=minutes)
    s.navigations = navigations
    if age_min is not None:
        s.started_at = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    return s


class TestSeuilDeNavigations:
    def test_sous_le_seuil_on_garde_la_session(self):
        assert session(nav=150, navigations=149)._recyclage_du() is None

    def test_au_seuil_on_recycle(self):
        raison = session(nav=150, navigations=150)._recyclage_du()
        assert raison is not None and "navigations" in raison

    def test_au_dela_du_seuil_aussi(self):
        assert session(nav=150, navigations=400)._recyclage_du() is not None


class TestSeuilDAge:
    def test_session_jeune_conservee(self):
        assert session(minutes=45, age_min=44)._recyclage_du() is None

    def test_session_agee_recyclee(self):
        raison = session(minutes=45, age_min=46)._recyclage_du()
        assert raison is not None and "anciennete" in raison

    def test_sans_date_de_demarrage_l_age_ne_declenche_rien(self):
        """Une session jamais demarree n'a pas d'age : ne pas planter dessus."""
        s = BrowserSession(name="Test", max_minutes=45)
        assert s.started_at is None
        assert s._recyclage_du() is None


class TestDesactivation:
    def test_zero_desactive_les_deux_bornes(self):
        """Le comportement d'origine reste accessible : 0 = illimite."""
        s = session(nav=0, minutes=0, age_min=10_000, navigations=999_999)
        assert s._recyclage_du() is None

    def test_valeurs_par_defaut_sans_borne(self):
        """Un appelant qui ne demande rien garde l'ancien comportement."""
        s = BrowserSession(name="Test")
        s.navigations = 10_000
        s.started_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert s._recyclage_du() is None


class TestPremierSeuilAtteint:
    def test_les_deux_bornes_coexistent(self):
        """Peu importe laquelle se declenche : c'est la premiere qui compte."""
        beaucoup_navigue = session(nav=150, minutes=45, age_min=1, navigations=200)
        assert "navigations" in beaucoup_navigue._recyclage_du()

        vieille_mais_calme = session(nav=150, minutes=45, age_min=90, navigations=3)
        assert "anciennete" in vieille_mais_calme._recyclage_du()


class TestConfiguration:
    def test_les_valeurs_par_defaut_du_projet_sont_actives(self):
        """Une borne desactivee par megarde ramenerait le gel de 4 heures."""
        from surebet.config import settings
        assert settings.browser_recycle_navigations > 0
        assert settings.browser_recycle_minutes > 0
