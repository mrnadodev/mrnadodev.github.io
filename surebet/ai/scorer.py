"""Scoring de fiabilite des opportunites (spec MISSION §6.3).

Score 0-100 purement DETERMINISTE (l'IA ne calcule jamais le score, §6.4).
Combine : fraicheur des cotes, confiance d'appariement semantique, stabilite du
bookmaker, volatilite de la ligne, plausibilite (drapeau rouge si ROI > 25% sur
un marche majeur -> presque toujours une erreur d'appariement).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..normalizer.schema import Opportunity

MAJOR_MARKETS = {"1x2", "goals_total", "btts", "points_total"}
ALERT_SCORE_THRESHOLD = 70


@dataclass(slots=True)
class ScoringContext:
    """Signaux externes optionnels alimentant le score (defauts neutres)."""

    match_confidences: list[float] = field(default_factory=list)  # confiance normalisation par jambe
    bookmaker_stability: dict[str, float] = field(default_factory=dict)  # 0-1, freq annulations/limitations
    line_volatility_5min: float = 0.0  # ecart-type normalise de la ligne sur 5 min (0 = stable)
    now: datetime | None = None


def _freshness_score(opp: Opportunity, now: datetime) -> float:
    """0-1 : penalite forte si une cote a plus de 60s."""
    age = (now - opp.detected_at.astimezone(timezone.utc)).total_seconds()
    if age <= 15:
        return 1.0
    if age <= 60:
        return 1.0 - 0.5 * (age - 15) / 45  # 1.0 -> 0.5 sur [15s, 60s]
    return max(0.0, 0.5 - (age - 60) / 120)  # chute rapide au-dela de 60s


def _matching_confidence_score(ctx: ScoringContext) -> float:
    if not ctx.match_confidences:
        return 0.85  # neutre-optimiste si non renseigne (cotes issues des regles deterministes)
    return sum(ctx.match_confidences) / len(ctx.match_confidences)


def _bookmaker_stability_score(opp: Opportunity, ctx: ScoringContext) -> float:
    if not ctx.bookmaker_stability:
        return 0.85
    scores = [ctx.bookmaker_stability.get(leg.bookmaker, 0.85) for leg in opp.legs]
    return sum(scores) / len(scores) if scores else 0.85


def _volatility_score(ctx: ScoringContext) -> float:
    return max(0.0, 1.0 - min(ctx.line_volatility_5min, 1.0))


def _plausibility_score(opp: Opportunity) -> float:
    """Drapeau rouge : ROI > 25% sur marche majeur -> quasi certainement une
    erreur d'appariement, pas une vraie opportunite (spec MISSION §6.3).
    """
    if opp.market_type in MAJOR_MARKETS and opp.roi_pct > 25.0:
        return 0.0
    if opp.roi_pct > 40.0:  # ROI extreme sur n'importe quel marche : suspect
        return 0.15
    return 1.0


def score_opportunity(opp: Opportunity, ctx: ScoringContext | None = None) -> int:
    """Score 0-100 ; alerter si >= 70 (spec MISSION §6.3, §8)."""
    ctx = ctx or ScoringContext()
    now = (ctx.now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    # Plausibilite = multiplicateur (drapeau rouge = veto, spec MISSION §6.3) :
    # une opportunite implausible voit son score effondre quels que soient les
    # autres signaux. Les 4 autres composantes forment une somme ponderee (poids
    # sommant a 1) representant la qualite de l'opportunite si elle est reelle.
    quality_components = [
        (_freshness_score(opp, now), 0.30),
        (_matching_confidence_score(ctx), 0.35),
        (_bookmaker_stability_score(opp, ctx), 0.20),
        (_volatility_score(ctx), 0.15),
    ]
    quality = sum(value * weight for value, weight in quality_components)
    score = quality * _plausibility_score(opp)
    return round(max(0.0, min(1.0, score)) * 100)
