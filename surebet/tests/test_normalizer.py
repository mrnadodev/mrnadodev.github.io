"""Tests du normalizer deterministe (spec MISSION §6.1, §9).

>= 50 paires positives (libelles reels + variantes FR/EN/creole/symboles) et
>= 20 pieges negatifs (faux appariements a refuser, ou ambiguites a renvoyer
avec confidence basse pour forcer le fallback IA).
"""
import pytest

from surebet.normalizer.markets import normalize_market_label
from surebet.normalizer.teams import best_team_match, teams_match

HOME = "Ghana"
AWAY = "Colombie"

POSITIVE_CASES = [
    # (market_label, selection_label, expected_market_type, expected_selection, expected_line)
    ("Nombre de buts", "> 0.5", "goals_total", "over", 0.5),
    ("Nombre de buts", "< 0.5", "goals_total", "under", 0.5),
    ("Nombre de buts", "plus 2.5", "goals_total", "over", 2.5),
    ("Nombre de buts", "moins 2.5", "goals_total", "under", 2.5),
    ("Total de buts", "Over 3.5", "goals_total", "over", 3.5),
    ("Total de buts", "Under 3.5", "goals_total", "under", 3.5),
    ("Buts total", "anwo 1.5", "goals_total", "over", 1.5),
    ("Buts total", "anba 1.5", "goals_total", "under", 1.5),
    ("Total tirs", "> 7.5", "shots_total", "over", 7.5),
    ("Tirs total Ghana", "moins 7.5", "shots_team", "under", 7.5),
    ("Ghana Total Shots", "Under 7.5", "shots_team", "under", 7.5),
    ("Tirs total Ghana", "Anba 7.5", "shots_team", "under", 7.5),
    ("Tirs cadres total", "> 3.5", "shots_on_target_total", "over", 3.5),
    ("Shots on Target Total", "under 4.5", "shots_on_target_total", "under", 4.5),
    ("Tirs cadres Ghana", "moins 2.5", "shots_on_target_team", "under", 2.5),
    ("Total corners", "> 9.5", "corners_total", "over", 9.5),
    ("Corners total match", "moins 8.5", "corners_total", "under", 8.5),
    ("Total corners 1ere mi-temps", "over 4.5", "corners_total_1h", "over", 4.5),
    ("Corners 2eme mi-temps", "under 5.5", "corners_total_2h", "under", 5.5),
    ("Total tacles", "> 20.5", "tackles_total", "over", 20.5),
    ("Tackles Total", "under 18.5", "tackles_total", "under", 18.5),
    ("Total fautes", "> 22.5", "fouls_total", "over", 22.5),
    ("Fouls total", "moins 19.5", "fouls_total", "under", 19.5),
    ("Total cartons", "> 3.5", "cards_total", "over", 3.5),
    ("Cards total", "under 4.5", "cards_total", "under", 4.5),
    ("Total arrets du gardien", "> 5.5", "saves_total", "over", 5.5),
    ("Goalkeeper Saves Total", "under 3.5", "saves_total", "under", 3.5),
    ("Total VAR", "+0.5", "var_total", "over", 0.5),
    ("VAR reviews", "-0.5", "var_total", "under", 0.5),
    ("Total hors-jeu", "> 2.5", "offside_total", "over", 2.5),
    ("Offside Total", "under 1.5", "offside_total", "under", 1.5),
    ("Total de buts de Ghana", "> 1.5", "goals_team", "over", 1.5),
    ("Total de buts de Colombie", "< 1.5", "goals_team", "under", 1.5),
    ("Les deux equipes marquent", "Oui", "btts", "over", None),
    ("Les deux equipes marquent", "Non", "btts", "under", None),
    ("Both teams to score", "Yes", "btts", "over", None),
    ("Both Teams To Score", "No", "btts", "under", None),
    ("Resultat du match", "1", "1x2", "home", None),
    ("Resultat du match", "X", "1x2", "draw", None),
    ("Resultat du match", "2", "1x2", "away", None),
    ("Match Result", "Home", "1x2", "home", None),
    ("Match Result", "Draw", "1x2", "draw", None),
    ("Match Result", "Away", "1x2", "away", None),
    ("Resultat du match 1ere mi-temps", "1", "1x2_1h", "home", None),
    ("Resultat du match mi-temps 2", "X", "1x2_2h", "draw", None),
    ("Points totaux", "> 210.5", "points_total", "over", 210.5),
    ("Total Points", "under 199.5", "points_total", "under", 199.5),
    ("Points de Ghana", "> 100.5", "points_team", "over", 100.5),
    ("Total rebonds", "> 45.5", "rebounds_total", "over", 45.5),
    ("Rebounds Total", "under 40.5", "rebounds_total", "under", 40.5),
    ("Total passes decisives", "> 22.5", "assists_total", "over", 22.5),
    ("Assists Total", "under 20.5", "assists_total", "under", 20.5),
    ("Nombre de buts", "Over 2.5", "goals_total", "over", 2.5),
    ("Nombre de buts", "superieur 2.5", "goals_total", "over", 2.5),
    ("Nombre de buts", "inferieur 2.5", "goals_total", "under", 2.5),
]

NEGATIVE_CASES = [
    # Faux appariements : tirs != tirs cadres
    ("Total tirs", "> 7.5"),
    ("Tirs cadres total", "> 3.5"),
]


@pytest.mark.parametrize(
    "market_label,selection_label,expected_type,expected_selection,expected_line",
    POSITIVE_CASES,
)
def test_positive_market_matches(market_label, selection_label, expected_type, expected_selection, expected_line):
    result = normalize_market_label(market_label, selection_label, HOME, AWAY)
    assert result is not None, f"Aucune regle n'a matche: {market_label!r} / {selection_label!r}"
    assert result.market_type == expected_type
    assert result.selection == expected_selection
    if expected_line is not None:
        assert result.line == pytest.approx(expected_line)
    assert result.confidence >= 0.9, "Un cas positif documente doit avoir une confiance elevee"


def test_shots_vs_shots_on_target_are_distinct_markets():
    """Piege negatif : "tirs" != "tirs cadres" (spec MISSION §6.1)."""
    shots = normalize_market_label("Total tirs", "> 7.5", HOME, AWAY)
    shots_on_target = normalize_market_label("Tirs cadres total", "> 3.5", HOME, AWAY)
    assert shots.market_type == "shots_total"
    assert shots_on_target.market_type == "shots_on_target_total"
    assert shots.market_type != shots_on_target.market_type


def test_corners_first_half_vs_full_match_are_distinct_markets():
    """Piege negatif : "corners 1ere mi-temps" != "corners match" (spec MISSION §6.1)."""
    full_match = normalize_market_label("Total corners", "> 9.5", HOME, AWAY)
    first_half = normalize_market_label("Total corners 1ere mi-temps", "> 4.5", HOME, AWAY)
    assert full_match.market_type == "corners_total"
    assert first_half.market_type == "corners_total_1h"
    assert full_match.market_type != first_half.market_type


class TestPromoVariantsAreExcluded:
    """Regression : les variantes promotionnelles sont EXCLUES de l'arbitrage.

    Releve en test live sur Paryaj Lakay, un meme match expose simultanement
    "Resultat du match", "... 2UP", "... (rembourse si match nul)" et
    "... (rembourse si CSKA Moscou gagne)". Tous ces titres matchent
    "Resultat du match" et leurs selections matchent 1/X/2.

    Elles sont rejetees plutot que regroupees : leurs regles de paiement
    different entre elles, donc un market_type commun recreerait le faux
    appariement qu'on veut eviter.
    """

    @pytest.mark.parametrize("selection", ["1: 2UP", "X: 2UP", "2: 2UP"])
    def test_2up_is_rejected(self, selection):
        assert normalize_market_label("Resultat du match 2UP", selection, HOME, AWAY) is None

    @pytest.mark.parametrize("label", [
        "Resultat du match (rembourse si match nul)",
        "Resultat du match (rembourse si Ghana gagne)",
        "Resultat du match avec assurance",
        "Match result cashback",
        "Match result insurance",
    ])
    def test_refund_and_insurance_variants_are_rejected(self, label):
        assert normalize_market_label(label, "1", HOME, AWAY) is None

    def test_distinct_promos_cannot_collide(self):
        """Deux promos differentes ne doivent pas se retrouver sous un meme type."""
        a = normalize_market_label("Resultat du match (rembourse si match nul)", "1", HOME, AWAY)
        b = normalize_market_label("Resultat du match 2UP", "1: 2UP", HOME, AWAY)
        assert a is None and b is None

    def test_plain_1x2_is_still_accepted(self):
        assert normalize_market_label("Resultat du match", "1", HOME, AWAY).market_type == "1x2"
        assert normalize_market_label("Match Result", "Home", HOME, AWAY).market_type == "1x2"
        assert normalize_market_label("Resultat du match", "X", HOME, AWAY).selection == "draw"


def test_1x2_first_half_vs_full_match_are_distinct():
    full_match = normalize_market_label("Resultat du match", "1", HOME, AWAY)
    first_half = normalize_market_label("Resultat du match 1ere mi-temps", "1", HOME, AWAY)
    assert full_match.market_type != first_half.market_type


def test_team_scoped_goals_distinct_from_match_goals():
    match_goals = normalize_market_label("Nombre de buts", "> 2.5", HOME, AWAY)
    team_goals = normalize_market_label("Total de buts de Ghana", "> 1.5", HOME, AWAY)
    assert match_goals.team_scope is None
    assert team_goals.team_scope == "home"
    assert match_goals.market_type != team_goals.market_type


def test_goals_team_wrong_team_not_confused():
    ghana_goals = normalize_market_label("Total de buts de Ghana", "> 1.5", HOME, AWAY)
    colombie_goals = normalize_market_label("Total de buts de Colombie", "> 1.5", HOME, AWAY)
    assert ghana_goals.team_scope == "home"
    assert colombie_goals.team_scope == "away"
    assert ghana_goals.team_scope != colombie_goals.team_scope


def test_ambiguous_handicap_gets_low_confidence():
    """Handicap europeen/asiatique : structure ambigue -> confidence < 0.9, fallback IA."""
    result = normalize_market_label("Handicap Europeen", "1 (0:1)", HOME, AWAY)
    assert result is not None
    assert result.confidence < 0.9


def test_market_keyword_without_line_gets_low_confidence():
    """Mot-cle de marche detecte mais ligne/direction introuvable -> confidence basse."""
    result = normalize_market_label("Total corners", "Oui", HOME, AWAY)
    assert result is not None
    assert result.confidence < 0.9


@pytest.mark.parametrize(
    "market_label,selection_label",
    [
        ("Buteur suivant", "Cauteruccio, Martin"),
        ("Score exact", "1:0"),
        ("Nombre de sets", "> 3.5"),
        ("Vainqueur du tournoi", "Ghana"),
        ("Meilleur marqueur", "Braithwaite"),
        ("Double chance et total buts combine", "1 et + 2.5"),
        ("Temps mort", "Oui"),
        ("Penalty accorde", "Oui"),
        ("Nombre de sets remportes", "2"),
        ("Type de mise exotique inconnu", "valeur"),
        ("Prochain but", "Ghana"),
        ("Minute du premier but", "> 30.5"),
        ("Carton rouge dans le match", "Oui"),
        ("Nombre total de remplacements", "> 5.5"),
        ("Coup franc direct transforme", "Non"),
        ("Nom du capitaine", "Ghana"),
        ("Duree des arrets de jeu", "> 3.5"),
        ("Championnat vainqueur", "Ghana"),
        ("Nom de l'arbitre", "M. Dupont"),
        ("Blague interne du bookmaker", "??"),
    ],
)
def test_unknown_labels_return_none(market_label, selection_label):
    """Pieges negatifs : libelles hors-perimetre qui ne doivent pas matcher a tort."""
    result = normalize_market_label(market_label, selection_label, HOME, AWAY)
    if result is not None:
        assert result.confidence < 0.9


class TestTeamsFuzzyMatching:
    @pytest.mark.parametrize(
        "name_a,name_b",
        [
            ("Manchester United", "Man Utd"),
            ("Paris Saint-Germain", "PSG"),
            ("Real Madrid", "Real"),
            ("Club Bolivar", "Bolivar"),
            ("Gremio Porto Alegrense RS", "Gremio"),
        ],
    )
    def test_known_aliases_match(self, name_a, name_b):
        assert teams_match(name_a, name_b, threshold=85) is True

    def test_different_teams_do_not_match(self):
        assert teams_match("Manchester United", "Manchester City", threshold=85) is False

    def test_best_team_match_selects_correct_candidate(self):
        candidates = ["Manchester United", "Manchester City", "Liverpool"]
        result = best_team_match("Man Utd", candidates, threshold=85)
        assert result is not None
        assert result.candidate == "Manchester United"


class TestSquadLevelNeverConfused:
    """Regression : une equipe U-23 / reserve / feminine n'est PAS l'equipe premiere.

    Piege releve en test live : "Eltham Redbacks U-23" et "Eltham Redbacks"
    obtiennent un score de 88 (> seuil 85). Les apparier a produit un faux
    surebet a +5,73 % de ROI — en realite deux matchs distincts, joues a
    08:15 et 10:30, cotes 1.37/4.79/5.72 et 1.91/3.69/3.15.
    """

    @pytest.mark.parametrize("senior,other", [
        ("Eltham Redbacks", "Eltham Redbacks U-23"),
        ("Melbourne Serbia", "Melbourne Serbia U-23"),
        ("Real Madrid", "Real Madrid U19"),
        ("FC Barcelona", "FC Barcelona Youth"),
        ("Arsenal", "Arsenal Reserves"),
        ("Chelsea", "Chelsea Women"),
        ("Liverpool", "Liverpool Academy"),
    ])
    def test_senior_never_matches_other_squad(self, senior, other):
        assert teams_match(senior, other, threshold=85) is False

    @pytest.mark.parametrize("a,b", [
        ("Eltham Redbacks U-23", "Eltham Redbacks U23"),
        ("Real Madrid U19", "Real Madrid U-19"),
        ("Arsenal Reserves", "Arsenal Reserve"),
    ])
    def test_same_squad_level_still_matches(self, a, b):
        assert teams_match(a, b, threshold=85) is True

    def test_best_team_match_excludes_other_squad_levels(self):
        candidates = ["Eltham Redbacks", "Eltham Redbacks U-23"]
        senior = best_team_match("Eltham Redbacks FC", candidates, threshold=85)
        youth = best_team_match("Eltham Redbacks U-23", candidates, threshold=85)
        assert senior is not None and senior.candidate == "Eltham Redbacks"
        assert youth is not None and youth.candidate == "Eltham Redbacks U-23"

    def test_no_eligible_candidate_returns_none(self):
        assert best_team_match("Eltham Redbacks U-23", ["Eltham Redbacks"], threshold=85) is None

    def test_squad_marker_detection(self):
        from surebet.normalizer.teams import squad_marker

        assert squad_marker("Eltham Redbacks") is None
        assert squad_marker("Eltham Redbacks U-23") == "youth"
        assert squad_marker("Arsenal Reserves") == "reserve"
        assert squad_marker("Chelsea Women") == "women"

    def test_plain_teams_are_unaffected(self):
        """Le garde-fou ne doit pas casser les appariements legitimes."""
        assert teams_match("Manchester United", "Man Utd", threshold=85) is True
        assert teams_match("Paris Saint-Germain", "PSG", threshold=85) is True
