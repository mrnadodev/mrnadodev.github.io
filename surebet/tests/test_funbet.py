"""Tests de la section FunBet (parsing, pricing, extraction HTML).

Les libelles de reference sont ceux captures en live sur Paryaj Lakay
(/sports/manual-odds-boosts, juillet 2026).
"""
from datetime import datetime, timezone

import pytest

from surebet.funbet.parser import parse_funbet
from surebet.funbet.pricing import value_funbet
from surebet.funbet.scrape import extract_funbets_from_html
from surebet.normalizer.schema import Odd, make_match_id

DAY = datetime(2026, 7, 24, 11, 30, tzinfo=timezone.utc)


class TestParser:
    def test_shots_and_corners_combo(self):
        fb = parse_funbet(
            "UTA Arad - ASC Otelul Galati",
            "Otelul reussit 8 tirs cadres ou + & obtient 8 corners ou + (source: Opta)",
            45,
        )
        assert fb.boosted_odds == 45
        assert len(fb.conditions) == 2
        c0, c1 = fb.conditions
        assert c0.kind == "threshold" and c0.stat == "shots_on_target" and c0.line == 7.5
        assert c1.kind == "threshold" and c1.stat == "corners" and c1.line == 7.5

    def test_win_btts_each_team_corners(self):
        fb = parse_funbet(
            "Viborg FF - Odense Boldklub",
            "Viborg gagne & les deux equipes marquent & chaque equipe obtient 6 corners ou +",
            20,
        )
        kinds = [c.kind for c in fb.conditions]
        assert kinds == ["win", "btts", "threshold"]
        assert fb.conditions[0].team == "Viborg FF"
        assert fb.conditions[2].each_team is True
        assert fb.conditions[2].stat == "corners" and fb.conditions[2].line == 5.5

    def test_source_annotation_is_stripped(self):
        fb = parse_funbet("A - B", "A gagne (source: leagueofireland.ie)", 3.0)
        assert "source" not in fb.conditions[0].raw.lower()

    def test_teams_extracted_from_match(self):
        fb = parse_funbet("UTA Arad - ASC Otelul Galati", "A gagne", 2.0)
        assert fb.home_team == "UTA Arad"
        assert fb.away_team == "ASC Otelul Galati"

    def test_unknown_condition_flags_unparsable(self):
        fb = parse_funbet("A - B", "quelque chose d'incomprehensible xyz", 5.0)
        assert fb.is_parsable is False
        assert fb.conditions[0].unknown is True

    def test_threshold_line_is_n_minus_half(self):
        """'8 corners ou +' => Over 7.5 (au moins 8)."""
        fb = parse_funbet("A - B", "obtient 8 corners ou +", 4.0)
        assert fb.conditions[0].line == 7.5


class TestPricing:
    def _pool(self, legs):
        """legs : liste de (market_type, selection, line, team_scope, odds)."""
        mid = make_match_id("Real Madrid", "Barcelona", DAY)
        base = dict(
            bookmaker="1xBet", sport="football", competition="X", match_id=mid,
            home_team="Real Madrid", away_team="Barcelona", start_time=DAY,
            url="https://1xbet/e", scraped_at=datetime.now(timezone.utc),
        )
        return [
            Odd(market_type=mtype, n_outcomes=3 if mtype == "1x2" else 2,
                selection=sel, line=line, team_scope=scope, odds=price, **base)
            for (mtype, sel, line, scope, price) in legs
        ]

    def test_full_valuation_win_and_btts(self):
        """FunBet 'Real Madrid gagne & BTTS' price depuis 1xBet."""
        pool = self._pool([
            ("1x2", "home", None, None, 1.50),
            ("btts", "over", None, None, 1.80),
        ])
        fb = parse_funbet("Real Madrid - Barcelona", "Real Madrid gagne & les deux equipes marquent", 3.20)
        val = value_funbet(fb, pool)
        assert val.complete is True
        # prix juste = 1.50 * 1.80 = 2.70 ; edge = 3.20/2.70 - 1 = 18.5%
        assert val.fair_odds == pytest.approx(2.70, abs=1e-6)
        assert val.edge_pct == pytest.approx(18.52, abs=0.1)

    def test_positive_edge_flags_value(self):
        pool = self._pool([
            ("1x2", "home", None, None, 2.0),
            ("btts", "over", None, None, 2.0),
        ])
        fb = parse_funbet("Real Madrid - Barcelona", "Real Madrid gagne & les deux equipes marquent", 5.0)
        val = value_funbet(fb, pool)
        # fair 4.0, boost 5.0 -> +25% edge
        assert val.edge_pct == pytest.approx(25.0, abs=0.1)

    def test_incomplete_when_condition_unpriceable(self):
        """Corners absents de 1xBet -> valuation incomplete, aucun edge annonce."""
        pool = self._pool([("1x2", "home", None, None, 1.5)])
        fb = parse_funbet("Real Madrid - Barcelona",
                          "Real Madrid gagne & obtient 8 corners ou +", 6.0)
        val = value_funbet(fb, pool)
        assert val.complete is False
        assert val.edge_pct is None
        assert val.unpriced_count == 1
        # la jambe chiffrable reste exposee (utile au hedge manuel)
        priced = [p for p in val.priced if p.fair_odds is not None]
        assert len(priced) == 1 and priced[0].fair_odds == 1.5

    def test_no_matching_1xbet_match(self):
        pool = self._pool([("1x2", "home", None, None, 1.5)])
        fb = parse_funbet("Equipe Inconnue - Autre Equipe", "Equipe Inconnue gagne", 2.0)
        val = value_funbet(fb, pool)
        assert val.complete is False


class TestExtractHtml:
    # structure reelle : un .manual-odds-boost par match, contenant plusieurs
    # .manual-odds-with-event-item (chacun .odds-name + .value).
    HTML = """
    <div class="manual-odds-boost">
      <a href="/sports/event/79197883">UTA Arad - ASC Otelul Galati</a>
      <div class="manual-odds-with-event-item">
        <span class="odds-name">Otelul reussit 8 tirs cadres ou + &amp; obtient 8 corners ou + (source: Opta)</span>
        <span class="value">45</span><span class="value">45</span>
      </div>
      <div class="manual-odds-with-event-item">
        <span class="odds-name">UTA Arad gagne &amp; les deux equipes marquent</span>
        <span class="value">4.5</span><span class="value">4.5</span>
      </div>
    </div>
    """

    def test_extracts_all_boosts(self):
        fbs = extract_funbets_from_html(self.HTML)
        assert len(fbs) == 2
        assert fbs[0].boosted_odds == 45
        assert fbs[1].boosted_odds == 4.5

    def test_match_title_and_conditions(self):
        fbs = extract_funbets_from_html(self.HTML)
        assert fbs[0].match == "UTA Arad - ASC Otelul Galati"
        assert fbs[0].home_team == "UTA Arad"
        assert fbs[1].conditions[0].kind == "win"

    def test_empty_html(self):
        assert extract_funbets_from_html("<div></div>") == []
