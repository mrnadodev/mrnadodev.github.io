"""Pricing des FunBets a partir des cotes 1xBet.

Une FunBet "A & B & C" a un prix juste = produit des cotes de A, B, C (sous
hypothese d'independance, approximation raisonnable pour des conditions de
nature differente : victoire, corners, tirs). Si la cote boostee depasse ce
prix juste, il y a un edge positif -- la "surebet a fort pourcentage".

Honnetete : on ne chiffre que les conditions dont on trouve la cote chez 1xBet.
Si une condition n'est pas chiffrable (marche absent du flux), la valuation est
marquee `complete=False` et AUCUN edge n'est annonce (un produit partiel
surestimerait la probabilite et donnerait un faux edge).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..normalizer.schema import Odd
from ..normalizer.teams import teams_similar
from .parser import Condition, FunBet

# stat FunBet -> market_type canonique (total / par equipe)
STAT_TO_MARKET = {
    ("shots_on_target", False): "shots_on_target_total",
    ("shots_on_target", True): "shots_on_target_team",
    ("shots", False): "shots_total",
    ("shots", True): "shots_team",
    ("corners", False): "corners_total",
    ("corners", True): "corners_team",
    ("goals", False): "goals_total",
    ("goals", True): "goals_team",
    ("cards", False): "cards_total",
    ("cards", True): "cards_team",
    ("fouls", False): "fouls_total",
    ("fouls", True): "fouls_team",
}


@dataclass(slots=True)
class PricedLeg:
    condition: Condition
    fair_odds: float | None      # None si non chiffrable
    bookmaker: str | None = None
    detail: str = ""


@dataclass(slots=True)
class FunBetValuation:
    funbet: FunBet
    priced: list[PricedLeg] = field(default_factory=list)
    fair_odds: float | None = None       # produit, si complet
    edge_pct: float | None = None        # (boost/fair - 1) x 100, si complet
    complete: bool = False               # toutes les conditions chiffrees ?

    @property
    def unpriced_count(self) -> int:
        return sum(1 for p in self.priced if p.fair_odds is None)


def _find_odd(pool: list[Odd], match_id: str, market_type: str,
              selection: str, line: float | None, team_scope: str | None) -> Odd | None:
    best = None
    for o in pool:
        if o.match_id != match_id or o.market_type != market_type:
            continue
        if o.selection != selection or o.team_scope != team_scope:
            continue
        if line is not None and o.line != line:
            continue
        if best is None or o.odds > best.odds:
            best = o
    return best


def _match_pool(pool: list[Odd], funbet: FunBet) -> list[Odd]:
    """Cotes 1xBet du meme match que la FunBet (appariement flou des equipes)."""
    if not funbet.home_team or not funbet.away_team:
        return []
    out = []
    for o in pool:
        if teams_similar(o.home_team, funbet.home_team) and \
           teams_similar(o.away_team, funbet.away_team):
            out.append(o)
    return out


def _price_condition(cond: Condition, match_odds: list[Odd]) -> PricedLeg:
    if not match_odds:
        return PricedLeg(cond, None, detail="match absent de 1xBet")
    mid = match_odds[0].match_id
    book = match_odds[0].bookmaker

    if cond.kind == "win":
        scope = _which_side(cond, match_odds)
        if scope is None:
            return PricedLeg(cond, None, detail="equipe non identifiee")
        sel = "home" if scope == "home" else "away"
        o = _find_odd(match_odds, mid, "1x2", sel, None, None)
        return PricedLeg(cond, o.odds if o else None, book, "victoire (1X2)")

    if cond.kind == "btts":
        o = _find_odd(match_odds, mid, "btts", "over", None, None)
        return PricedLeg(cond, o.odds if o else None, book, "BTTS oui")

    if cond.kind == "threshold":
        return _price_threshold(cond, match_odds, mid, book)

    return PricedLeg(cond, None, detail="condition non reconnue")


def _price_threshold(cond: Condition, match_odds: list[Odd], mid: str, book: str) -> PricedLeg:
    if cond.each_team:
        mt = STAT_TO_MARKET.get((cond.stat, True))
        if mt is None:
            return PricedLeg(cond, None, detail=f"stat {cond.stat} inconnue")
        home_o = _find_odd(match_odds, mid, mt, "over", cond.line, "home")
        away_o = _find_odd(match_odds, mid, mt, "over", cond.line, "away")
        if home_o and away_o:
            return PricedLeg(cond, home_o.odds * away_o.odds, book,
                             f"{cond.stat} >= {cond.line + 0.5:g} chaque equipe")
        return PricedLeg(cond, None, detail=f"{cond.stat} par equipe absent de 1xBet")

    mt = STAT_TO_MARKET.get((cond.stat, cond.team is not None))
    if mt is None:
        return PricedLeg(cond, None, detail=f"stat {cond.stat} inconnue")
    scope = _which_side(cond, match_odds) if cond.team else None
    o = _find_odd(match_odds, mid, mt, "over", cond.line, scope)
    if o:
        return PricedLeg(cond, o.odds, book, f"{cond.stat} >= {cond.line + 0.5:g}")
    return PricedLeg(cond, None, detail=f"{cond.stat} (ligne {cond.line}) absent de 1xBet")


def _which_side(cond: Condition, match_odds: list[Odd]) -> str | None:
    """Cote domicile/exterieur pour l'equipe de la condition."""
    ref = match_odds[0]
    if cond.team is None:
        return None
    if teams_similar(cond.team, ref.home_team):
        return "home"
    if teams_similar(cond.team, ref.away_team):
        return "away"
    return None


def value_funbet(funbet: FunBet, pool_1xbet: list[Odd]) -> FunBetValuation:
    """Chiffre une FunBet contre les cotes 1xBet et estime l'edge."""
    match_odds = _match_pool(pool_1xbet, funbet)
    priced = [_price_condition(c, match_odds) for c in funbet.conditions]

    valuation = FunBetValuation(funbet=funbet, priced=priced)
    if priced and all(p.fair_odds is not None for p in priced):
        fair = 1.0
        for p in priced:
            fair *= p.fair_odds
        valuation.fair_odds = fair
        valuation.edge_pct = (funbet.boosted_odds / fair - 1.0) * 100.0
        valuation.complete = True
    return valuation
