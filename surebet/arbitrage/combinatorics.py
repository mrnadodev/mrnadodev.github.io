"""Generation des combinaisons cross-bookmakers (2 et 3 issues, spec MISSION §2-4)."""
from __future__ import annotations

from collections import defaultdict
from itertools import product
from typing import Iterator

from ..normalizer.schema import Odd

GroupKey = tuple[str, str, float | None, str | None]  # match_id, market_type, line, team_scope


def group_by_match_market(pool: list[Odd]) -> dict[GroupKey, list[Odd]]:
    """Regroupe les cotes par (match_id, market_type, line, team_scope)."""
    groups: dict[GroupKey, list[Odd]] = defaultdict(list)
    for odd in pool:
        if odd.is_stale:
            continue
        key = (odd.match_id, odd.market_type, odd.line, odd.team_scope)
        groups[key].append(odd)
    return groups


def two_way_pairs(group: list[Odd]) -> Iterator[tuple[Odd, Odd]]:
    """Paires (over, under) ou (home, away) de bookmakers differents dans un groupe binaire."""
    side_a = [o for o in group if o.selection in ("over", "home")]
    side_b = [o for o in group if o.selection in ("under", "away")]
    for a, b in product(side_a, side_b):
        if a.bookmaker != b.bookmaker:
            yield a, b


def three_way_triplets(group: list[Odd]) -> Iterator[tuple[Odd, Odd, Odd]]:
    """Triplets (home, draw, away), au moins deux bookmakers distincts (spec MISSION §4)."""
    homes = [o for o in group if o.selection == "home"]
    draws = [o for o in group if o.selection == "draw"]
    aways = [o for o in group if o.selection == "away"]
    for h, d, a in product(homes, draws, aways):
        if len({h.bookmaker, d.bookmaker, a.bookmaker}) >= 2:
            yield h, d, a


def best_two_way(group: list[Odd]) -> tuple[Odd, Odd] | None:
    """Meilleure cote par cote (max) pour chaque cote d'un marche binaire, tous bookmakers."""
    side_a = [o for o in group if o.selection in ("over", "home")]
    side_b = [o for o in group if o.selection in ("under", "away")]
    if not side_a or not side_b:
        return None
    best_a = max(side_a, key=lambda o: o.odds)
    best_b = max(side_b, key=lambda o: o.odds)
    if best_a.bookmaker == best_b.bookmaker:
        alt_b = max((o for o in side_b if o.bookmaker != best_a.bookmaker), key=lambda o: o.odds, default=None)
        alt_a = max((o for o in side_a if o.bookmaker != best_b.bookmaker), key=lambda o: o.odds, default=None)
        if alt_b is not None and (alt_a is None or alt_b.odds >= alt_a.odds):
            return best_a, alt_b
        if alt_a is not None:
            return alt_a, best_b
        return None
    return best_a, best_b


def best_three_way(group: list[Odd]) -> tuple[Odd, Odd, Odd] | None:
    """Retient la cote maximale disponible tous bookmakers confondus pour chaque issue 1X2."""
    homes = [o for o in group if o.selection == "home"]
    draws = [o for o in group if o.selection == "draw"]
    aways = [o for o in group if o.selection == "away"]
    if not homes or not draws or not aways:
        return None
    best_h = max(homes, key=lambda o: o.odds)
    best_d = max(draws, key=lambda o: o.odds)
    best_a = max(aways, key=lambda o: o.odds)
    if len({best_h.bookmaker, best_d.bookmaker, best_a.bookmaker}) >= 2:
        return best_h, best_d, best_a
    # Un seul bookmaker domine les 3 meilleures cotes : cherche la meilleure alternative
    best_triplet = None
    best_margin = float("inf")
    for h, d, a in three_way_triplets(group):
        m = 1 / h.odds + 1 / d.odds + 1 / a.odds
        if m < best_margin:
            best_margin = m
            best_triplet = (h, d, a)
    return best_triplet
