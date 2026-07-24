"""Repartition des mises (spec MISSION §5.2, §5.3, §5.6)."""
from __future__ import annotations

from .detector import implied_margin


def split_stakes(bankroll: float, odds: list[float], round_to: int | None = 1) -> list[float]:
    """Repartit `bankroll` pour que le retour soit identique quelle que soit l'issue.

    Mise_i = B / (Cote_i x M).  Sigma Mise_i = B et Gain_i = Mise_i x Cote_i = B/M constant.

    `round_to` est le nombre de decimales (0 = HTG entier, None = pas d'arrondi).
    En arrondi entier (round_to=0), la mission (§5.6) demande un ajustement
    residuel sur la mise de l'issue a la cote la plus elevee, plus sensible
    sur les paniers a 3 issues, pour que la somme des mises reste egale a B.
    """
    if not odds:
        return []
    margin = implied_margin(odds)
    raw_stakes = [bankroll / (o * margin) for o in odds]

    if round_to is None:
        return raw_stakes

    rounded = [round(s, round_to) for s in raw_stakes]

    if round_to == 0 and len(odds) > 1:
        idx_max = max(range(len(odds)), key=lambda i: odds[i])
        others_sum = sum(s for i, s in enumerate(rounded) if i != idx_max)
        rounded[idx_max] = round(bankroll - others_sum, 0)

    return rounded


def guaranteed_profit(bankroll: float, odds: list[float]) -> float:
    """Profit = B/M - B = B x (1/M - 1)."""
    margin = implied_margin(odds)
    return bankroll * (1.0 / margin - 1.0)


def gains_per_leg(stakes: list[float], odds: list[float]) -> list[float]:
    """Gain_i = Mise_i x Cote_i pour chaque issue (doit etre constant avant arrondi)."""
    return [s * o for s, o in zip(stakes, odds)]


def min_guaranteed_gain(stakes: list[float], odds: list[float]) -> float:
    """min(Gain_i) apres arrondi : n'alerter que si > bankroll (§5.6)."""
    return min(gains_per_leg(stakes, odds))


def clamp_to_bookmaker_limits(
    stakes: list[float], min_stakes: list[float], max_stakes: list[float]
) -> list[float]:
    """Respecte les mises min/max de chaque bookmaker pour chaque jambe."""
    return [
        max(mn, min(mx, s)) for s, mn, mx in zip(stakes, min_stakes, max_stakes)
    ]
