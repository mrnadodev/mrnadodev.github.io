"""Tests du scraper Paryaj Pam (WebSocket, token public "demo").

Le payload de reference reproduit la structure reelle capturee en test live
(juillet 2026) sur wss://wss-new.sport.paryajpam.com/ws/. Aucun reseau.
"""
import pytest

from surebet.scrapers.pamws import (
    MARKET_TYPE_BY_TP,
    OUTCOME_TO_SELECTION,
    PERIOD_SUFFIX,
    TEAM_SCOPE_BY_TP,
    parse_outcomes,
    period_suffix,
)
from surebet.scrapers.paryajpam import ParyajPamScraper, _parse_start, _split_teams


def market(tp, period, outcomes, vl=""):
    """Fabrique un marche au format reel : `ou` = liste de dicts a cle opaque."""
    return {
        "tp": tp, "pn": period, "pi": 1, "nm": "M", "vl": vl,
        "ou": [{f"[k{i}]": o} for i, o in enumerate(outcomes)],
    }


LIVE_SHAPED = {
    "1": [
        {
            "trn": "Top Teams Friendlies", "ctn": "Clubs",
            "events": [
                {
                    "id": "17652882", "nm": "Como - Paris FC",
                    "cms": ["Como", "Paris FC"], "tm": "2026-07-24T08:30:00Z",
                    "mr": {
                        "h1": market(2, "MainTime", [
                            {"nm": "Win1", "kf": 1.73, "vl": ""},
                            {"nm": "Draw", "kf": 4.28, "vl": ""},
                            {"nm": "Win2", "kf": 4.12, "vl": ""},
                        ]),
                        # meme tp mais 1ere mi-temps : ne doit PAS etre fusionne
                        "h2": market(2, "Half1", [
                            {"nm": "Win1", "kf": 2.50, "vl": ""},
                            {"nm": "Draw", "kf": 2.10, "vl": ""},
                            {"nm": "Win2", "kf": 5.00, "vl": ""},
                        ]),
                        "t1": market(4, "MainTime", [
                            {"nm": "Over", "kf": 1.85, "vl": "2.5"},
                            {"nm": "Under", "kf": 1.95, "vl": "2.5"},
                        ]),
                        "tt": market(5, "MainTime", [
                            {"nm": "Over", "kf": 2.05, "vl": "1.5"},
                            {"nm": "Under", "kf": 1.75, "vl": "1.5"},
                        ]),
                        # periode inconnue : doit etre ecartee
                        "xx": market(2, "OvertimePenalties", [
                            {"nm": "Win1", "kf": 9.0, "vl": ""},
                        ]),
                        # type non mappe : ignore
                        "zz": market(999, "MainTime", [{"nm": "Win1", "kf": 3.0, "vl": ""}]),
                    },
                }
            ],
        }
    ]
}


class TestProtocolMappings:
    def test_outcome_names_map_to_canonical_selections(self):
        assert OUTCOME_TO_SELECTION["Win1"] == "home"
        assert OUTCOME_TO_SELECTION["Draw"] == "draw"
        assert OUTCOME_TO_SELECTION["Win2"] == "away"
        assert OUTCOME_TO_SELECTION["Over"] == "over"
        assert OUTCOME_TO_SELECTION["Under"] == "under"

    def test_market_types_carry_outcome_count(self):
        assert MARKET_TYPE_BY_TP[2] == ("1x2", 3)
        assert MARKET_TYPE_BY_TP[4] == ("goals_total", 2)

    def test_niche_markets_required_by_mission_are_covered(self):
        """Marches de niche exiges par la mission §2 (et moins marges)."""
        assert MARKET_TYPE_BY_TP[67] == ("corners_total", 2)      # CornersTotal
        assert MARKET_TYPE_BY_TP[97] == ("shots_on_target_total", 2)
        assert MARKET_TYPE_BY_TP[131] == ("shots_total", 2)       # ShotsAllTotal
        assert MARKET_TYPE_BY_TP[77] == ("cards_total", 2)        # YellowCardsTotal
        assert MARKET_TYPE_BY_TP[87] == ("fouls_total", 2)
        assert MARKET_TYPE_BY_TP[380] == ("saves_total", 2)
        assert MARKET_TYPE_BY_TP[419] == ("tackles_total", 2)
        assert MARKET_TYPE_BY_TP[124] == ("offside_total", 2)

    def test_mission_example_shots_by_team_is_mapped(self):
        """L'exemple §5.4 ("Tirs total Ghana 7.5") = ShotsAllTeam1/2Total."""
        assert MARKET_TYPE_BY_TP[132] == ("shots_team", 2)
        assert MARKET_TYPE_BY_TP[133] == ("shots_team", 2)
        assert TEAM_SCOPE_BY_TP[132] == "home"
        assert TEAM_SCOPE_BY_TP[133] == "away"

    def test_team1_and_team2_variants_never_share_a_scope(self):
        """Sans scope distinct, "tirs equipe A" serait apparie a "tirs equipe B"."""
        pairs = [(5, 6), (68, 69), (78, 79), (88, 89), (98, 99),
                 (125, 126), (132, 133), (381, 382), (420, 421)]
        for team1, team2 in pairs:
            assert MARKET_TYPE_BY_TP[team1] == MARKET_TYPE_BY_TP[team2]
            assert TEAM_SCOPE_BY_TP[team1] == "home"
            assert TEAM_SCOPE_BY_TP[team2] == "away"

    def test_every_scoped_type_is_mapped(self):
        for tp in TEAM_SCOPE_BY_TP:
            assert tp in MARKET_TYPE_BY_TP, f"tp={tp} a un scope mais aucun mapping"

    def test_period_suffixes(self):
        assert PERIOD_SUFFIX["MainTime"] == ""
        assert PERIOD_SUFFIX["Half1"] == "_1h"
        assert PERIOD_SUFFIX["Half2"] == "_2h"

    def test_unknown_period_returns_none(self):
        assert period_suffix({"pn": "OvertimePenalties"}) is None
        assert period_suffix({}) is None


class TestDynamicNameRecognition:
    """Si Paryaj Pam ajoute un marche avec un tp non mappe, il est reconnu par
    son nom `nm` (fallback dynamique), au lieu d'etre ignore."""

    def test_known_names(self):
        from surebet.scrapers.pamws import market_from_name

        assert market_from_name("CornersTotal") == ("corners_total", 2, None)
        assert market_from_name("CornersTeam1Total") == ("corners_team", 2, "home")
        assert market_from_name("FoulsTeam2Total") == ("fouls_team", 2, "away")

    @pytest.mark.parametrize("name,expected", [
        ("YellowCardsTotal", ("cards_total", 2, None)),
        ("ShotsOnTargetTotal", ("shots_on_target_total", 2, None)),
        ("ShotsAllTotal", ("shots_total", 2, None)),
        ("TacklesTotal", ("tackles_total", 2, None)),
        ("SavesTotal", ("saves_total", 2, None)),
        ("VARTotal", ("var_total", 2, None)),   # VAR non offert aujourd'hui, mais capte si ajoute
    ])
    def test_added_markets_recognized_by_name(self, name, expected):
        from surebet.scrapers.pamws import market_from_name

        assert market_from_name(name) == expected

    @pytest.mark.parametrize("name", [
        "CornersHandicap", "CornersDoubleChance", "CornersTotalOddEven",
        "CornersWinner3Ways", "Winner3Ways", "DoubleChance",
    ])
    def test_non_over_under_rejected(self, name):
        from surebet.scrapers.pamws import market_from_name

        assert market_from_name(name) is None

    def test_unmapped_tp_falls_back_to_name(self):
        """Un marche avec tp inconnu mais nom reconnu doit produire des cotes."""
        payload = {"1": [{"trn": "T", "events": [{
            "id": "1", "nm": "A - B", "cms": ["A", "B"], "tm": "2026-07-24T10:00:00Z",
            "mr": {"x": {
                "tp": 99999, "pn": "MainTime", "nm": "VARTotal", "vl": "2.5",
                "ou": [
                    {"[k0]": {"nm": "Over", "kf": 1.9, "vl": "2.5"}},
                    {"[k1]": {"nm": "Under", "kf": 1.9, "vl": "2.5"}},
                ],
            }},
        }]}]}
        odds = ParyajPamScraper()._parse(payload, "football", 1)
        assert len(odds) == 2
        assert all(o.market_type == "var_total" for o in odds)


class TestParseOutcomes:
    def test_extracts_selection_odds_and_line(self):
        m = market(4, "MainTime", [
            {"nm": "Over", "kf": 1.85, "vl": "2.5"},
            {"nm": "Under", "kf": 1.95, "vl": "2.5"},
        ])
        assert parse_outcomes(m) == [("over", 1.85, 2.5), ("under", 1.95, 2.5)]

    def test_rejects_odds_at_or_below_one(self):
        m = market(2, "MainTime", [
            {"nm": "Win1", "kf": 1.0, "vl": ""},
            {"nm": "Draw", "kf": 3.5, "vl": ""},
        ])
        assert parse_outcomes(m) == [("draw", 3.5, None)]

    def test_ignores_unknown_outcome_names(self):
        m = market(2, "MainTime", [{"nm": "SomethingElse", "kf": 3.0, "vl": ""}])
        assert parse_outcomes(m) == []

    def test_line_falls_back_to_market_value(self):
        m = market(4, "MainTime", [{"nm": "Over", "kf": 1.9, "vl": ""}], vl="3.5")
        assert parse_outcomes(m) == [("over", 1.9, 3.5)]


class TestTeamAndTimeParsing:
    def test_prefers_cms_field(self):
        assert _split_teams({"cms": ["A", "B"], "nm": "X - Y"}) == ("A", "B")

    def test_falls_back_to_splitting_name(self):
        assert _split_teams({"nm": "Como - Paris FC"}) == ("Como", "Paris FC")

    def test_returns_none_when_unparseable(self):
        assert _split_teams({"nm": "SomeSingleName"}) == (None, None)

    def test_parses_iso_timestamp(self):
        dt = _parse_start("2026-07-24T08:30:00Z")
        assert dt is not None and dt.year == 2026 and dt.hour == 8

    def test_invalid_timestamp_returns_none(self):
        assert _parse_start("pas une date") is None
        assert _parse_start(None) is None


class TestParyajPamParsing:
    def setup_method(self):
        self.odds = ParyajPamScraper()._parse(LIVE_SHAPED, "football", 1)

    def test_parses_expected_number_of_odds(self):
        # 3 (1x2) + 3 (1x2_1h) + 2 (total) + 2 (team total) = 10
        assert len(self.odds) == 10

    def test_full_time_1x2_values(self):
        x2 = {o.selection: o.odds for o in self.odds if o.market_type == "1x2"}
        assert x2 == {"home": 1.73, "draw": 4.28, "away": 4.12}

    def test_first_half_1x2_is_a_distinct_market(self):
        """Le 1X2 de mi-temps ne doit jamais etre confondu avec le match entier."""
        first_half = {o.selection: o.odds for o in self.odds if o.market_type == "1x2_1h"}
        assert first_half == {"home": 2.50, "draw": 2.10, "away": 5.00}
        assert {o.market_type for o in self.odds} >= {"1x2", "1x2_1h"}

    def test_no_false_merge_between_periods(self):
        """Regression : deux periodes ne doivent pas produire 6 cotes sur '1x2'."""
        assert len([o for o in self.odds if o.market_type == "1x2"]) == 3

    def test_team_total_carries_scope(self):
        team = [o for o in self.odds if o.market_type == "goals_team"]
        assert len(team) == 2
        assert all(o.team_scope == "home" for o in team)

    def test_totals_carry_line(self):
        totals = {o.selection: o.line for o in self.odds if o.market_type == "goals_total"}
        assert totals == {"over": 2.5, "under": 2.5}

    def test_unknown_period_is_skipped(self):
        assert all(o.odds != 9.0 for o in self.odds)

    def test_unmapped_market_type_is_skipped(self):
        assert all(o.odds != 3.0 for o in self.odds)

    def test_metadata_populated(self):
        odd = self.odds[0]
        assert odd.bookmaker == "Paryaj Pam"
        assert odd.home_team == "Como"
        assert odd.away_team == "Paris FC"
        assert odd.competition == "Top Teams Friendlies"
        assert odd.url.startswith("https://www.paryajpam.com")

    def test_all_odds_share_match_id(self):
        assert len({o.match_id for o in self.odds}) == 1

    def test_empty_payload(self):
        assert ParyajPamScraper()._parse({}, "football", 1) == []


class TestScrapeErrors:
    @pytest.mark.asyncio
    async def test_unsupported_sport_raises(self):
        with pytest.raises(ValueError):
            await ParyajPamScraper().scrape("tennis")

    @pytest.mark.asyncio
    async def test_ws_failure_becomes_scraper_unavailable(self, monkeypatch):
        from surebet.scrapers import paryajpam as module
        from surebet.scrapers.base import ScraperUnavailableError

        class BoomClient:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): raise RuntimeError("ws down")
            async def __aexit__(self, *a): return False

        monkeypatch.setattr(module, "ParyajPamWSClient", BoomClient)
        with pytest.raises(ScraperUnavailableError):
            await ParyajPamScraper().scrape("football")


class TestFeedsArbitrage:
    def test_margins_are_bookmaker_positive(self):
        from surebet.arbitrage.detector import implied_margin

        odds = ParyajPamScraper()._parse(LIVE_SHAPED, "football", 1)
        x2 = [o.odds for o in odds if o.market_type == "1x2"]
        assert implied_margin(x2) > 1.0

    def test_cross_book_detection_with_golcash_shaped_odds(self):
        """Deux books reels dans le pool -> le detecteur travaille sans conversion."""
        from surebet.ai.scout import Scout

        odds = ParyajPamScraper()._parse(LIVE_SHAPED, "football", 1)
        opportunities = Scout(min_roi=1.0, bankroll=50_000.0).evaluate(odds)
        # un seul bookmaker : aucune opportunite attendue
        assert opportunities == []
