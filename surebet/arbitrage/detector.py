"""Detection d'arbitrage 2 et 3 issues (spec MISSION §5.1, §5.4, §5.5).

L'IA ne remplace jamais ce calcul : implied_margin/is_surebet/roi_percent
sont purement deterministes et font autorite (spec MISSION §6, §6.4).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..normalizer.schema import Leg, Odd, Opportunity, make_match_id
from .combinatorics import best_three_way, best_two_way, group_by_match_market


def implied_margin(odds: list[float]) -> float:
    """M = Sigma (1 / Cote_i) pour i = 1..n. Fonction generique, n quelconque."""
    if not odds:
        raise ValueError("odds ne peut pas etre vide")
    return sum(1.0 / o for o in odds)


def is_surebet(odds: list[float], threshold: float = 1.0) -> bool:
    """M < threshold -> surebet, profit garanti."""
    return implied_margin(odds) < threshold


def roi_percent(odds: list[float]) -> float:
    """ROI% = (1/M - 1) x 100."""
    margin = implied_margin(odds)
    return (1.0 / margin - 1.0) * 100.0


def best_odds_per_outcome(pool: list[Odd]) -> dict[str, Odd]:
    """Agregation 1X2 : meilleure cote par issue (home/draw/away), tous bookmakers."""
    best: dict[str, Odd] = {}
    for odd in pool:
        current = best.get(odd.selection)
        if current is None or odd.odds > current.odds:
            best[odd.selection] = odd
    return best


def _match_label(odd: Odd) -> str:
    return f"{odd.home_team} - {odd.away_team}"


def _make_opportunity(
    legs_odds: tuple[Odd, ...],
    market_type: str,
    line: float | None,
    team_scope: str | None,
    bankroll: float,
    min_roi: float,
) -> Opportunity | None:
    odds_values = [o.odds for o in legs_odds]
    margin = implied_margin(odds_values)
    roi = roi_percent(odds_values)
    if margin >= 1.0 or roi < min_roi:
        return None

    ref = legs_odds[0]
    legs = [
        Leg(
            bookmaker=o.bookmaker,
            selection=o.selection,
            odds=o.odds,
            url=o.url,
            event_label=f"{o.market_type} {o.selection}" + (f" {o.line}" if o.line is not None else ""),
        )
        for o in legs_odds
    ]
    return Opportunity(
        match_id=ref.match_id,
        sport=ref.sport,
        match_label=_match_label(ref),
        match_date=ref.start_time,
        market_type=market_type,
        line=line,
        team_scope=team_scope,
        n_outcomes=len(legs_odds),
        legs=legs,
        margin=margin,
        roi_pct=roi,
        bankroll=bankroll,
        profit=bankroll * (1.0 / margin - 1.0),
        detected_at=datetime.now(timezone.utc),
    )


def find_two_way(pool: list[Odd], min_roi: float = 1.0, bankroll: float = 0.0) -> list[Opportunity]:
    """Detecte les surebets 2 issues (Over/Under, 1X2 binaire...) cross-bookmakers."""
    opportunities: list[Opportunity] = []
    for (_, market_type, line, team_scope), group in group_by_match_market(pool).items():
        if group and group[0].n_outcomes != 2:
            continue
        pair = best_two_way(group)
        if pair is None:
            continue
        opp = _make_opportunity(pair, market_type, line, team_scope, bankroll, min_roi)
        if opp is not None:
            opportunities.append(opp)
    return sorted(opportunities, key=lambda o: o.roi_pct, reverse=True)


def find_three_way(pool: list[Odd], min_roi: float = 1.0, bankroll: float = 0.0) -> list[Opportunity]:
    """Detecte les surebets 3 issues (1X2) cross-bookmakers, meilleure cote par issue."""
    opportunities: list[Opportunity] = []
    for (_, market_type, line, team_scope), group in group_by_match_market(pool).items():
        if group and group[0].n_outcomes != 3:
            continue
        triplet = best_three_way(group)
        if triplet is None:
            continue
        opp = _make_opportunity(triplet, market_type, line, team_scope, bankroll, min_roi)
        if opp is not None:
            opportunities.append(opp)
    return sorted(opportunities, key=lambda o: o.roi_pct, reverse=True)


__all__ = [
    "implied_margin",
    "is_surebet",
    "roi_percent",
    "best_odds_per_outcome",
    "find_two_way",
    "find_three_way",
    "make_match_id",
]
