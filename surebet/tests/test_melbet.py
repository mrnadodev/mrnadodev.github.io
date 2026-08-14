"""MelBet : parametrage du scraper 1xBet, et refus des paires du meme groupe.

Verifie en direct le 12 aout 2026 : melbet.com expose le meme flux LineFeed
que 1xBet, avec le meme codage (G, T) des marches. Seul `partner` change —
8 au lieu de 151.

Mais la meme mesure a montre que les deux enseignes donnent 466 cotes
identiques sur 530 comparables, soit 87,9 %. Elles partagent leur moteur de
prix. Un arbitrage detecte entre elles viendrait donc presque toujours d'un
decalage de rafraichissement, et serait annule au guichet : ces tests
verifient qu'il ne peut pas etre propose.
"""
from datetime import datetime, timedelta, timezone

from surebet.arbitrage.detector import find_three_way, find_two_way, operateur
from surebet.normalizer.schema import Odd, make_match_id
from surebet.scrapers.melbet import MELBET_PARTNER, MelBetScraper
from surebet.scrapers.xbet import XBET_PARTNER, XBetScraper

HOME, AWAY = "Lyon", "Nice"
START = datetime.now(timezone.utc) + timedelta(days=1)


def odd(bookmaker, selection, cote, n=3, market="1x2"):
    return Odd(
        bookmaker=bookmaker, sport="football", competition="Ligue 1",
        match_id=make_match_id(HOME, AWAY, START), home_team=HOME, away_team=AWAY,
        start_time=START, market_type=market, n_outcomes=n, selection=selection,
        line=None, team_scope=None, odds=cote,
        url=f"https://{bookmaker}.test/e", scraped_at=datetime.now(timezone.utc),
    )


class TestScraper:
    def test_herite_du_scraper_1xbet(self):
        """Meme plateforme : on parametre, on ne duplique pas 200 lignes."""
        assert issubclass(MelBetScraper, XBetScraper)

    def test_nom_et_partner_propres(self):
        s = MelBetScraper()
        assert s.bookmaker_name == "MelBet"
        assert s.partner == MELBET_PARTNER == 8
        assert s.partner != XBET_PARTNER

    def test_url_du_flux_pointe_sur_melbet(self):
        s = MelBetScraper()
        u = s._feed_url(1)
        assert "melbet.com" in u and "partner=8" in u and "LineFeed" in u

    def test_la_carte_des_marches_est_partagee(self):
        """Une correction de mapping doit profiter aux deux bookmakers."""
        from surebet.scrapers import xbet
        assert MelBetScraper.__mro__[1] is XBetScraper
        assert xbet.MARKET_MAP  # la carte reste unique


class TestGroupes:
    def test_1xbet_et_melbet_sont_le_meme_operateur(self):
        assert operateur("1xBet") == operateur("MelBet")

    def test_les_haitiens_sont_independants(self):
        noms = ["Golcash", "Paryaj Pam", "Paryaj Lakay"]
        groupes = {operateur(n) for n in noms}
        assert len(groupes) == 3
        assert operateur("1xBet") not in groupes

    def test_casse_et_espaces_ignores(self):
        assert operateur("  melbet ") == operateur("MELBET") == operateur("MelBet")


class TestRefusDesPairesDuMemeGroupe:
    def test_arbitrage_1xbet_melbet_refuse(self):
        """Cotes tres attractives, mais meme groupe : rien ne doit sortir."""
        pool = [odd("1xBet", "home", 2.10, n=2, market="goals_total"),
                odd("MelBet", "away", 2.10, n=2, market="goals_total")]
        assert find_two_way(pool, min_roi=0.1) == []

    def test_arbitrage_melbet_golcash_accepte(self):
        """C'est FACE aux bookmakers haitiens que MelBet apporte quelque chose."""
        pool = [odd("MelBet", "over", 2.10, n=2, market="goals_total"),
                odd("Golcash", "under", 2.10, n=2, market="goals_total")]
        opps = find_two_way(pool, min_roi=0.1, bankroll=10_000.0)
        assert len(opps) == 1
        assert {l.bookmaker for l in opps[0].legs} == {"MelBet", "Golcash"}

    def test_trois_issues_toutes_du_meme_groupe_refusees(self):
        pool = [odd("1xBet", "home", 3.4), odd("MelBet", "draw", 3.6),
                odd("1xBet", "away", 3.5)]
        assert find_three_way(pool, min_roi=0.1) == []

    def test_trois_issues_avec_un_independant_acceptees(self):
        """Deux jambes chez un meme groupe restent normales s'il y a un tiers."""
        pool = [odd("1xBet", "home", 3.4), odd("MelBet", "draw", 3.6),
                odd("Paryaj Pam", "away", 3.5)]
        opps = find_three_way(pool, min_roi=0.1, bankroll=10_000.0)
        assert len(opps) == 1
