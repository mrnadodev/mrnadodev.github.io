"""Tests du client Swarm et du scraper Golcash (BetConstruct).

Le payload de reference reproduit la structure reelle observee en test live
(juillet 2026) sur wss://eu-swarm-newm.betconstruct.com/ avec site_id=1345.
Aucun reseau : le client WebSocket est un double de test.
"""
import pytest

from surebet.scrapers.golcash import GolcashScraper, _extract_line
from surebet.scrapers.swarm import (
    EVENT_TYPE_TO_SELECTION,
    MARKET_TYPE_MAP,
    pattern_market,
    resolve_swarm_market,
)


class TestDynamicMarketRecognition:
    """Repond a : si Golcash AJOUTE des marches de niche (cartons, fautes,
    tirs...) sur un match, le systeme les reconnait-il sans modif du code ?

    Oui : resolve_swarm_market combine la liste blanche explicite ET une
    reconnaissance par motif des noms BetConstruct.
    """

    def test_known_corners_via_whitelist(self):
        assert resolve_swarm_market("CornersOverUnder") == ("corners_total", 2, None)
        assert resolve_swarm_market("HomeTeamCornersOverUnder") == ("corners_team", 2, "home")

    @pytest.mark.parametrize("swarm_type,expected", [
        ("YellowCardsOverUnder", ("cards_total", 2, None)),
        ("HomeTeamYellowCardsOverUnder", ("cards_team", 2, "home")),
        ("AwayTeamYellowCardsOverUnder", ("cards_team", 2, "away")),
        ("FoulsOverUnder", ("fouls_total", 2, None)),
        ("ShotsOnTargetOverUnder", ("shots_on_target_total", 2, None)),
        ("TotalShotsOverUnder", ("shots_total", 2, None)),
        ("TacklesOverUnder", ("tackles_total", 2, None)),
        ("OffsidesOverUnder", ("offside_total", 2, None)),
        ("GoalKicksOverUnder", ("goalkicks_total", 2, None)),
        ("SavesOverUnder", ("saves_total", 2, None)),
        ("ThrowInsOverUnder", ("throwins_total", 2, None)),
    ])
    def test_added_niche_markets_auto_recognized(self, swarm_type, expected):
        """Marches non presents aujourd'hui mais que l'operateur pourrait ajouter."""
        assert resolve_swarm_market(swarm_type) == expected

    def test_half_time_and_second_half_suffixes(self):
        assert pattern_market("HalfTimeFoulsOverUnder")[0] == "fouls_total_1h"
        assert pattern_market("2ndHalfCardsOver/Under")[0] == "cards_total_2h"

    @pytest.mark.parametrize("swarm_type", [
        "AsianHandicap", "CornerHandicap", "CornerOddEven", "P1XP2",
        "CorrectScore", "BothTeamsToScore", "HalfTimeResult",
    ])
    def test_non_over_under_markets_rejected(self, swarm_type):
        """Handicap / odd-even / 1x2 ne sont pas des paires over/under -> ignores."""
        assert pattern_market(swarm_type) is None

    def test_shots_on_target_matched_before_shots(self):
        """L'ordre des mots-cles evite de classer 'tirs cadres' en 'tirs'."""
        assert pattern_market("ShotsOnTargetOverUnder")[0] == "shots_on_target_total"
        assert pattern_market("TotalShotsOverUnder")[0] == "shots_total"

# Structure reelle Swarm : sport -> competition -> game -> market -> event
LIVE_SHAPED_PAYLOAD = {
    "sport": {
        "1": {
            "id": 1, "name": "Football", "alias": "Soccer",
            "competition": {
                "10": {
                    "id": 10, "name": "NPL Victoria 2",
                    "game": {
                        "100": {
                            "id": 100,
                            "team1_name": "Keilor Park SC",
                            "team2_name": "Bayside Argonauts FC",
                            "start_ts": 1785000000,
                            "market": {
                                "1000": {
                                    "id": 1000, "type": "P1XP2", "name": "Match Result",
                                    "event": {
                                        "1": {"id": 1, "type": "P1", "name": "W1", "price": 2.52},
                                        "2": {"id": 2, "type": "X", "name": "Draw", "price": 3.61},
                                        "3": {"id": 3, "type": "P2", "name": "W2", "price": 2.34},
                                    },
                                },
                                "1001": {
                                    "id": 1001, "type": "OverUnder", "name": "Total Goals",
                                    "event": {
                                        "4": {"id": 4, "type": "Over", "name": "Over 2.5", "price": 1.85},
                                        "5": {"id": 5, "type": "Under", "name": "Under 2.5", "price": 1.95},
                                    },
                                },
                                "1002": {
                                    "id": 1002, "type": "BothTeamsToScore", "name": "BTTS",
                                    "event": {
                                        "6": {"id": 6, "type": "Yes", "name": "Yes", "price": 1.72},
                                        "7": {"id": 7, "type": "No", "name": "No", "price": 2.05},
                                    },
                                },
                                # marche non mappe : doit etre ignore sans casser
                                "1003": {
                                    "id": 1003, "type": "ExoticUnknownMarket", "name": "???",
                                    "event": {"8": {"id": 8, "type": "P1", "name": "x", "price": 5.0}},
                                },
                            },
                        }
                    },
                }
            },
        }
    }
}


class TestSwarmMappings:
    def test_event_types_cover_canonical_selections(self):
        assert EVENT_TYPE_TO_SELECTION["P1"] == "home"
        assert EVENT_TYPE_TO_SELECTION["X"] == "draw"
        assert EVENT_TYPE_TO_SELECTION["P2"] == "away"
        assert EVENT_TYPE_TO_SELECTION["Over"] == "over"
        assert EVENT_TYPE_TO_SELECTION["Under"] == "under"

    def test_market_types_carry_outcome_count(self):
        assert MARKET_TYPE_MAP["P1XP2"] == ("1x2", 3)
        assert MARKET_TYPE_MAP["OverUnder"] == ("goals_total", 2)
        assert MARKET_TYPE_MAP["BothTeamsToScore"] == ("btts", 2)

    def test_niche_markets_are_mapped(self):
        """Les marches de niche portent l'arbitrage : ils doivent etre couverts."""
        assert MARKET_TYPE_MAP["CornersOverUnder"] == ("corners_total", 2)
        assert MARKET_TYPE_MAP["HomeTeamCornersOverUnder"] == ("corners_team", 2)
        assert MARKET_TYPE_MAP["TeamWithMostCornersWithDraw"] == ("corners_1x2", 3)

    def test_half_time_markets_never_collide_with_full_match(self):
        """Un marche de mi-temps ne doit jamais partager le market_type du match."""
        from surebet.scrapers.swarm import MARKET_TYPE_MAP as M

        assert M["HalfTimeOverUnder"][0] != M["OverUnder"][0]
        assert M["HalfTimeCornersOverUnder"][0] != M["CornersOverUnder"][0]
        assert M["HalfTimeResult"][0] != M["P1XP2"][0]

    def test_team_scoped_markets_declare_their_side(self):
        from surebet.scrapers.swarm import SWARM_TEAM_SCOPE

        assert SWARM_TEAM_SCOPE["HomeTeamCornersOverUnder"] == "home"
        assert SWARM_TEAM_SCOPE["AwayTeamCornersOverUnder"] == "away"
        assert SWARM_TEAM_SCOPE["Team1OverUnder"] == "home"
        assert SWARM_TEAM_SCOPE["Team2OverUnder"] == "away"

    def test_every_team_scoped_type_is_also_mapped(self):
        """Coherence : tout marche portant un scope doit avoir un market_type."""
        from surebet.scrapers.swarm import SWARM_TEAM_SCOPE

        for swarm_type in SWARM_TEAM_SCOPE:
            assert swarm_type in MARKET_TYPE_MAP, f"{swarm_type} a un scope mais aucun mapping"


class TestExtractLine:
    @pytest.mark.parametrize("name,expected", [
        ("Over 2.5", 2.5), ("Under 0.5", 0.5), ("Total 10.5", 10.5),
        ("Yes", None), (None, None), ("Draw", None),
    ])
    def test_extracts_threshold(self, name, expected):
        assert _extract_line(name) == expected


class TestGolcashParsing:
    def setup_method(self):
        self.scraper = GolcashScraper()
        self.odds = self.scraper._parse(LIVE_SHAPED_PAYLOAD, "football")

    def test_parses_all_mapped_markets(self):
        # 3 (1x2) + 2 (over/under) + 2 (btts) ; le marche exotique est ignore
        assert len(self.odds) == 7

    def test_1x2_selections_and_prices(self):
        x2 = {o.selection: o.odds for o in self.odds if o.market_type == "1x2"}
        assert x2 == {"home": 2.52, "draw": 3.61, "away": 2.34}

    def test_over_under_carries_line(self):
        totals = {o.selection: (o.odds, o.line) for o in self.odds if o.market_type == "goals_total"}
        assert totals == {"over": (1.85, 2.5), "under": (1.95, 2.5)}

    def test_btts_mapped_to_binary_selections(self):
        btts = {o.selection: o.odds for o in self.odds if o.market_type == "btts"}
        assert btts == {"over": 1.72, "under": 2.05}

    def test_unmapped_market_is_skipped(self):
        assert all(o.market_type in {"1x2", "goals_total", "btts"} for o in self.odds)

    def test_metadata_is_populated(self):
        odd = self.odds[0]
        assert odd.bookmaker == "Golcash"
        assert odd.home_team == "Keilor Park SC"
        assert odd.away_team == "Bayside Argonauts FC"
        assert odd.competition == "NPL Victoria 2"
        assert odd.sport == "football"
        assert odd.url.startswith("https://www.golcashhaiti.com")

    def test_all_odds_share_same_match_id(self):
        assert len({o.match_id for o in self.odds}) == 1

    def test_invalid_prices_are_rejected(self):
        payload = {"sport": {"1": {"competition": {"1": {"name": "C", "game": {"1": {
            "id": 1, "team1_name": "A", "team2_name": "B", "start_ts": 1785000000,
            "market": {"1": {"type": "P1XP2", "event": {
                "1": {"type": "P1", "name": "W1", "price": 1.0},   # <= 1.0 rejetee
                "2": {"type": "X", "name": "D", "price": 3.5},
            }}},
        }}}}}}}
        odds = GolcashScraper()._parse(payload, "football")
        assert [o.odds for o in odds] == [3.5]

    def test_game_without_teams_is_skipped(self):
        payload = {"sport": {"1": {"competition": {"1": {"name": "C", "game": {"1": {
            "id": 1, "team1_name": None, "team2_name": "B", "start_ts": 1785000000, "market": {},
        }}}}}}}
        assert GolcashScraper()._parse(payload, "football") == []

    def test_empty_payload_returns_no_odds(self):
        assert GolcashScraper()._parse({}, "football") == []


class TestGolcashScrapeErrors:
    @pytest.mark.asyncio
    async def test_unsupported_sport_raises(self):
        with pytest.raises(ValueError):
            await GolcashScraper().scrape("tennis")

    @pytest.mark.asyncio
    async def test_swarm_failure_becomes_scraper_unavailable(self, monkeypatch):
        from surebet.scrapers import golcash as golcash_module
        from surebet.scrapers.base import ScraperUnavailableError

        class BoomClient:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): raise RuntimeError("swarm down")
            async def __aexit__(self, *a): return False

        monkeypatch.setattr(golcash_module, "SwarmClient", BoomClient)
        with pytest.raises(ScraperUnavailableError):
            await GolcashScraper().scrape("football")


class TestGolcashFeedsArbitrage:
    def test_live_shaped_odds_flow_into_detector(self):
        """Les cotes Swarm alimentent le detecteur sans conversion supplementaire."""
        from surebet.arbitrage.detector import implied_margin

        odds = GolcashScraper()._parse(LIVE_SHAPED_PAYLOAD, "football")
        x2 = [o.odds for o in odds if o.market_type == "1x2"]
        margin = implied_margin(x2)
        assert margin > 1.0  # marge bookmaker : pas d'arbitrage intra-book
        # 1/2.52 + 1/3.61 + 1/2.34 = 1.10118 -> marge bookmaker de 10.12 %
        assert margin == pytest.approx(1.10118, abs=1e-4)
