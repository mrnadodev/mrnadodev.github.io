"""Couverture d'un Funbet par ses conditions inverses.

Les tests verifient autant ce que le detecteur ACCEPTE que ce qu'il REFUSE :
une couverture incomplete ou mal appariee est pire que pas de signal du tout.
"""
from datetime import datetime, timedelta, timezone

import pytest

from surebet.funbet.arbitrage import find_funbet_arbitrage
from surebet.funbet.parser import Condition, FunBet
from surebet.normalizer.schema import Odd, make_match_id

HOME, AWAY = "Paris SG", "Marseille"
# Coup d'envoi toujours a venir : ne jamais figer de date dans un fixture.
START = datetime.now(timezone.utc) + timedelta(days=2)


def odd(bookmaker, market_type, selection, cote, line=None, scope=None):
    return Odd(
        bookmaker=bookmaker, sport="football", competition="Ligue 1",
        match_id=make_match_id(HOME, AWAY, START), home_team=HOME, away_team=AWAY,
        start_time=START, market_type=market_type, n_outcomes=2,
        selection=selection, line=line, team_scope=scope,
        odds=cote, url=f"https://{bookmaker}.test/e",
        scraped_at=datetime.now(timezone.utc),
    )


def funbet(cote, conditions, description="PSG +10 tirs et +10 fautes"):
    return FunBet(
        match=f"{HOME} - {AWAY}", home_team=HOME, away_team=AWAY,
        description=description, boosted_odds=cote,
        event_url="https://paryajlakay.test/funbet", conditions=conditions,
    )


def seuil(stat, line, team=HOME):
    return Condition(kind="threshold", team=team, stat=stat, line=line,
                     raw=f"+{line:g} {stat} {team}")


# ── Le cas qui marche ────────────────────────────────────────────────────

def test_funbet_modeste_sur_conditions_probables_donne_un_arbitrage():
    """Le bon regime : cote modeste, conditions faciles, couvertures a grosse cote.

    S = 1/1.6 + 1/8 + 1/8 = 0.875 -> ROI ~14 %.
    """
    fb = funbet(1.60, [seuil("shots", 3), seuil("fouls", 5)])
    pool = [
        odd("1xBet",   "shots_team", "under", 8.0, line=3, scope="home"),
        odd("Golcash", "fouls_team", "under", 8.0, line=5, scope="home"),
    ]
    opp = find_funbet_arbitrage(fb, pool, bankroll=10_000.0)
    assert opp is not None
    assert opp.n_outcomes == 3
    assert opp.roi_pct == pytest.approx(14.29, abs=0.1)
    # Les trois retours sont egaux : c'est ce qui rend le profit garanti.
    retours = [l.stake * l.odds for l in opp.legs]
    assert retours[0] == pytest.approx(retours[1], rel=1e-6)
    assert retours[1] == pytest.approx(retours[2], rel=1e-6)
    assert sum(l.stake for l in opp.legs) == pytest.approx(10_000.0, rel=1e-6)


def test_le_funbet_est_la_premiere_jambe_chez_paryaj_lakay():
    fb = funbet(1.60, [seuil("shots", 3), seuil("fouls", 5)])
    pool = [
        odd("1xBet",   "shots_team", "under", 8.0, line=3, scope="home"),
        odd("Golcash", "fouls_team", "under", 8.0, line=5, scope="home"),
    ]
    opp = find_funbet_arbitrage(fb, pool, bankroll=1000.0)
    assert opp.legs[0].bookmaker == "Paryaj Lakay"
    assert opp.legs[0].selection == "funbet"
    assert {l.bookmaker for l in opp.legs[1:]} == {"1xBet", "Golcash"}


# ── Les cas qu'il faut refuser ───────────────────────────────────────────

def test_gros_lot_a_cote_50_ne_peut_pas_etre_couvert():
    """Le regime impossible : conditions improbables, couvertures a cote basse.

    C'est le contre-exemple important : la cote du Funbet a beau etre
    enorme, la couverture double du cas « aucune des deux » coute trop cher.
    S = 1/50 + 1/1.15 + 1/1.15 = 1.76.
    """
    fb = funbet(50.0, [seuil("shots", 10), seuil("fouls", 10)])
    pool = [
        odd("1xBet",   "shots_team", "under", 1.15, line=10, scope="home"),
        odd("Golcash", "fouls_team", "under", 1.15, line=10, scope="home"),
    ]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_une_seule_condition_couverte_ne_suffit_pas():
    """Couverture incomplete : le pari resterait ouvert sur l'autre condition."""
    fb = funbet(1.60, [seuil("shots", 3), seuil("fouls", 5)])
    pool = [odd("1xBet", "shots_team", "under", 8.0, line=3, scope="home")]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_refuse_de_couvrir_avec_le_bookmaker_du_funbet():
    """Si Paryaj Lakay annule la promotion, les deux cotes tombent ensemble."""
    fb = funbet(1.60, [seuil("shots", 3), seuil("fouls", 5)])
    pool = [
        odd("Paryaj Lakay", "shots_team", "under", 8.0, line=3, scope="home"),
        odd("Paryaj Lakay", "fouls_team", "under", 8.0, line=5, scope="home"),
    ]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_refuse_une_ligne_differente():
    """« Plus de 3 tirs » ne se couvre pas par « moins de 5 tirs »."""
    fb = funbet(1.60, [seuil("shots", 3), seuil("fouls", 5)])
    pool = [
        odd("1xBet",   "shots_team", "under", 8.0, line=5, scope="home"),  # mauvaise ligne
        odd("Golcash", "fouls_team", "under", 8.0, line=5, scope="home"),
    ]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_refuse_une_condition_de_victoire():
    """L'inverse d'une victoire demande deux paris : le modele ne le couvre pas."""
    fb = funbet(1.60, [Condition(kind="win", team=HOME, raw="PSG gagne"),
                       seuil("fouls", 5)])
    pool = [
        odd("1xBet",   "1x2",        "draw",  8.0),
        odd("Golcash", "fouls_team", "under", 8.0, line=5, scope="home"),
    ]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_refuse_chaque_equipe():
    """« Chaque equipe » : l'inverse est « au moins une echoue », pas un pari unique."""
    c = Condition(kind="threshold", each_team=True, stat="shots", line=3,
                  raw="+3 tirs chaque equipe")
    fb = funbet(1.60, [c, seuil("fouls", 5)])
    pool = [
        odd("1xBet",   "shots_team", "under", 8.0, line=3, scope="home"),
        odd("Golcash", "fouls_team", "under", 8.0, line=5, scope="home"),
    ]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_refuse_un_funbet_non_analysable():
    c = Condition(kind="unknown", raw="quelque chose d'exotique", unknown=True)
    fb = funbet(1.60, [c])
    pool = [odd("1xBet", "shots_team", "under", 8.0, line=3, scope="home")]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_marge_juste_au_dessus_de_1_refusee():
    """S = 1.0 pile ne rapporte rien : ce n'est pas un surebet."""
    fb = funbet(2.0, [seuil("shots", 3)])
    pool = [odd("1xBet", "shots_team", "under", 2.0, line=3, scope="home")]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_meilleure_cote_retenue_quand_plusieurs_books_couvrent():
    """A conditions egales, la cote la plus haute reduit la mise de couverture."""
    fb = funbet(1.60, [seuil("shots", 3), seuil("fouls", 5)])
    pool = [
        odd("1xBet",      "shots_team", "under", 6.0, line=3, scope="home"),
        odd("Paryaj Pam", "shots_team", "under", 8.0, line=3, scope="home"),
        odd("Golcash",    "fouls_team", "under", 8.0, line=5, scope="home"),
    ]
    opp = find_funbet_arbitrage(fb, pool, bankroll=10_000.0)
    assert opp is not None
    jambe_tirs = next(l for l in opp.legs if "shots" in l.event_label)
    assert jambe_tirs.bookmaker == "Paryaj Pam"
    assert jambe_tirs.odds == 8.0


# ── Le piege releve sur les Funbets reels ────────────────────────────────

def test_refuse_une_condition_qui_nomme_une_equipe_sans_etre_rattachee():
    """Cas reel capture chez Paryaj Lakay, juillet 2026.

    « Otelul reussit 8 tirs cadres ou + » ressort du parseur avec
    team=None : il est donc lu comme un TOTAL DE MATCH. Le couvrir par
    « moins de 8 tirs dans le match » porterait sur un autre evenement.

    Le detecteur doit refuser plutot que de fabriquer cette fausse
    couverture — meme si des cotes inverses existent.
    """
    from surebet.funbet.parser import parse_funbet

    fb = parse_funbet(
        "UTA Arad - ASC Otelul Galati",
        "Otelul reussit 8 tirs cadres ou + & obtient 8 corners ou + (source: Opta)",
        45,
    )
    # Les conditions sont bien analysees, mais sans equipe rattachee.
    assert fb.is_parsable
    assert all(c.team is None for c in fb.conditions)

    pool = [
        odd("1xBet",   "shots_on_target_total", "under", 3.0, line=7.5),
        odd("Golcash", "corners_total",         "under", 3.0, line=7.5),
    ]
    assert find_funbet_arbitrage(fb, pool, bankroll=10_000.0) is None


def test_un_total_de_match_reel_reste_couvrable():
    """Non-regression : une condition qui ne nomme AUCUNE equipe passe."""
    fb = funbet(1.60, [seuil("corners", 4, team=None)],
                description="Le match compte 5 corners ou plus")
    pool = [odd("1xBet", "corners_total", "under", 8.0, line=4)]
    opp = find_funbet_arbitrage(fb, pool, bankroll=10_000.0)
    assert opp is not None
    assert opp.n_outcomes == 2


def test_diagnostic_explique_le_refus():
    """Un refus muet n'apprend rien : le diagnostic doit nommer la cause."""
    from surebet.funbet.arbitrage import diagnostiquer_funbet
    from surebet.funbet.parser import parse_funbet

    fb = parse_funbet(
        "Viborg FF - Odense Boldklub",
        "Viborg gagne & les deux equipes marquent & chaque equipe obtient 6 corners ou +",
        20,
    )
    raison = diagnostiquer_funbet(fb, [])
    assert "victoire" in raison


def test_diagnostic_chiffre_la_marge_quand_tout_est_couvrable():
    """Quand la structure convient, on veut savoir a quelle distance on est."""
    from surebet.funbet.arbitrage import diagnostiquer_funbet

    fb = funbet(1.20, [seuil("shots", 3), seuil("fouls", 5)])
    pool = [
        odd("1xBet",   "shots_team", "under", 3.0, line=3, scope="home"),
        odd("Golcash", "fouls_team", "under", 3.0, line=5, scope="home"),
    ]
    raison = diagnostiquer_funbet(fb, pool)
    assert "marge" in raison and "il manque" in raison
