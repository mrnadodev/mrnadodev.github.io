"""Tests des marches de niche 1xBet (sous-jeux GetGameZip).

Structure de reference issue du test live (juillet 2026) : sous-jeu "Corners"
avec la convention standard G=17 (total), G=15/62 (par equipe), T=9/10/11/12/13/14.
"""
from datetime import datetime, timezone

from surebet.scrapers.xbet_stats import (
    STAT_GT_MAP,
    find_stat_subgames,
    parse_stat_subgame,
    stat_from_tg,
)

START = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)


class TestTgMapping:
    def test_maps_french_stat_names(self):
        assert stat_from_tg("Corners") == "corners"
        assert stat_from_tg("Tirs Cadrés") == "shots_on_target"
        assert stat_from_tg("Fautes") == "fouls"
        assert stat_from_tg("Cartons jaunes") == "cards"
        assert stat_from_tg("Tacles") == "tackles"
        assert stat_from_tg("Dégagements de but") == "goalkicks"
        assert stat_from_tg("Sauvetages") == "saves"
        assert stat_from_tg("Contrôles VAR") == "var"
        assert stat_from_tg("Hors-jeu") == "offside"

    def test_accents_and_case_insensitive(self):
        assert stat_from_tg("tirs cadres") == "shots_on_target"
        assert stat_from_tg("CORNERS") == "corners"

    def test_unknown_returns_none(self):
        assert stat_from_tg("Possession de balle") is None
        assert stat_from_tg("") is None


class TestFindSubgames:
    def test_picks_wanted_subgames_first_occurrence(self):
        main = {"SG": [
            {"I": 111, "TG": "Corners"},
            {"I": 112, "TG": "Corners"},       # doublon -> ignore
            {"I": 113, "TG": "Tirs Cadrés"},
            {"I": 114, "TG": "Possession de balle"},
        ]}
        found = find_stat_subgames(main, {"corners", "shots_on_target"})
        assert found == {"corners": 111, "shots_on_target": 113}

    def test_ignores_unwanted(self):
        main = {"SG": [{"I": 1, "TG": "Fautes"}]}
        assert find_stat_subgames(main, {"corners"}) == {}


class TestParseStatSubgame:
    SUBGAME = {"E": [
        {"G": 17, "T": 9, "P": 7.5, "C": 1.229},   # total over
        {"G": 17, "T": 10, "P": 7.5, "C": 4.2},    # total under
        {"G": 15, "T": 11, "P": 5.5, "C": 1.98},   # home over
        {"G": 15, "T": 12, "P": 5.5, "C": 1.75},   # home under
        {"G": 62, "T": 13, "P": 4.5, "C": 2.17},   # away over
        {"G": 62, "T": 14, "P": 4.5, "C": 1.6},    # away under
        {"G": 1, "T": 1, "P": None, "C": 1.5},     # 1x2 corner -> ignore
        {"G": 17, "T": 9, "P": 8.5, "C": 1.0},     # cote <= 1 -> ignore
    ]}

    def _parse(self):
        from surebet.normalizer.schema import make_match_id
        mid = make_match_id("A", "B", START)
        return parse_stat_subgame(self.SUBGAME, "corners", "A", "B", mid,
                                  "Comp", "https://x/e", START,
                                  datetime.now(timezone.utc))

    def test_extracts_total_and_team_markets(self):
        odds = self._parse()
        # 2 total + 2 home + 2 away = 6
        assert len(odds) == 6

    def test_total_market_type_and_line(self):
        odds = self._parse()
        total = [o for o in odds if o.market_type == "corners_total"]
        assert {o.selection for o in total} == {"over", "under"}
        assert all(o.line == 7.5 for o in total)
        assert all(o.team_scope is None for o in total)

    def test_team_markets_carry_scope(self):
        odds = self._parse()
        team = [o for o in odds if o.market_type == "corners_team"]
        scopes = {(o.team_scope, o.selection): o.odds for o in team}
        assert scopes[("home", "over")] == 1.98
        assert scopes[("away", "over")] == 2.17

    def test_ignores_1x2_and_invalid_odds(self):
        odds = self._parse()
        assert all(o.odds > 1.0 for o in odds)
        assert all(o.market_type in ("corners_total", "corners_team") for o in odds)

    def test_gt_map_covers_over_under_total_and_teams(self):
        assert STAT_GT_MAP[(17, 9)] == ("over", None)
        assert STAT_GT_MAP[(15, 11)] == ("over", "home")
        assert STAT_GT_MAP[(62, 14)] == ("under", "away")
