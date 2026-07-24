"""Mapping deterministe libelle brut -> schema canonique (spec MISSION §3, §6.1).

Regles d'abord ; normalizer/ai_normalizer.py n'appelle le LLM que si aucune
regle ne matche ici, ou si la confiance retournee est < 0.9.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .teams import team_scope_in_label

LINE_RE = re.compile(r"(\d+(?:[.,]\d+)?)")

OVER_RE = re.compile(r">|(?<!\S)plus\b|\bover\b|\banwo\b|au[- ]dessus|superieur|(?<![a-zA-Z0-9])\+\s*\d", re.I)
UNDER_RE = re.compile(r"<|(?<!\S)moins\b|\bunder\b|\banba\b|en[- ]dessous|inferieur|(?<![a-zA-Z0-9])-\s*\d", re.I)

FIRST_HALF_RE = re.compile(r"1[eè]re?\s*mi[- ]?temps|1st\s*half|premye\s*mitan|mi[- ]?temps\s*1\b", re.I)
SECOND_HALF_RE = re.compile(r"2[eè]me\s*mi[- ]?temps|2nd\s*half|dezy[eè]m\s*mitan|mi[- ]?temps\s*2\b", re.I)

# "cadre/on target" doit exclure le marche generique "tirs" (piege negatif §6.1)
SHOTS_ON_TARGET_RE = re.compile(r"tirs?\s*cadr|shots?\s*on\s*target|tir\s*kadre", re.I)
SHOTS_RE = re.compile(r"\btirs?\b|\bshots?\b", re.I)

BTTS_RE = re.compile(
    r"les?\s*deux\s*[ée]quipes?\s*marquent|both\s*teams?\s*to\s*score|\bbtts\b|de\s*d[ie]\s*ekip\s*yo\s*mak[ei]",
    re.I,
)

RESULT_1X2_RE = re.compile(
    r"r[ée]sultat\s*(du\s*match)?|match\s*result|\b1x2\b|rezilta\s*match",
    re.I,
)

CORNERS_RE = re.compile(r"corners?", re.I)
TACKLES_RE = re.compile(r"tacles?|tackles?", re.I)
FOULS_RE = re.compile(r"fautes?|fouls?", re.I)
CARDS_RE = re.compile(r"cartons?|\bcards?\b", re.I)
SAVES_RE = re.compile(r"arr[êe]ts?\s*(du\s*)?gardien|goalkeeper\s*saves?|\bsaves?\b", re.I)
VAR_RE = re.compile(r"\bvar\b", re.I)
OFFSIDE_RE = re.compile(r"hors[- ]jeu|offsides?", re.I)
GOALS_RE = re.compile(r"nombre\s*de\s*buts|total\s*de\s*buts|\bbuts?\b|\bgoals?\b", re.I)
GOALS_EXCLUDE_RE = re.compile(r"premier|prochain|next\s*goal|score\s*exact|minute\s*du|double\s*chance", re.I)

POINTS_RE = re.compile(r"\bpoints?\b", re.I)
REBOUNDS_RE = re.compile(r"rebonds?|rebounds?", re.I)
ASSISTS_RE = re.compile(r"passes?\s*d[ée]cisives?|\bassists?\b", re.I)

HANDICAP_RE = re.compile(r"handicap", re.I)

SELECTION_HOME_RE = re.compile(r"^\s*1\b|domicile|home\b|\bkay\b", re.I)
SELECTION_DRAW_RE = re.compile(r"^\s*x\b|\bnul\b|draw\b|\begalit|\bnil\b|egal\b", re.I)
SELECTION_AWAY_RE = re.compile(r"^\s*2\b|ext[ée]rieur|away\b|\bdeyo\b", re.I)

YES_RE = re.compile(r"^\s*oui\b|^\s*yes\b|\bwi\b", re.I)
NO_RE = re.compile(r"^\s*non\b|^\s*no\b", re.I)


@dataclass(slots=True)
class MarketMatch:
    market_type: str
    selection: str  # "over"|"under"|"home"|"draw"|"away"
    n_outcomes: int
    line: float | None
    team_scope: str | None
    confidence: float


def _parse_line(text: str) -> float | None:
    match = LINE_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _period_suffix(label: str) -> str:
    if FIRST_HALF_RE.search(label):
        return "_1h"
    if SECOND_HALF_RE.search(label):
        return "_2h"
    return ""


def _over_under_selection(text: str) -> str | None:
    if OVER_RE.search(text):
        return "over"
    if UNDER_RE.search(text):
        return "under"
    if YES_RE.search(text):
        return "over"
    if NO_RE.search(text):
        return "under"
    return None


def _team_scope(label: str, home_team: str, away_team: str) -> str | None:
    return team_scope_in_label(label, home_team, away_team)


_BINARY_KEYWORDS: list[tuple[str, re.Pattern, re.Pattern | None]] = [
    ("shots_on_target_total", SHOTS_ON_TARGET_RE, None),
    ("shots_total", SHOTS_RE, None),
    ("corners_total", CORNERS_RE, None),
    ("tackles_total", TACKLES_RE, None),
    ("fouls_total", FOULS_RE, None),
    ("cards_total", CARDS_RE, None),
    ("saves_total", SAVES_RE, None),
    ("var_total", VAR_RE, None),
    ("offside_total", OFFSIDE_RE, None),
    ("goals_total", GOALS_RE, GOALS_EXCLUDE_RE),
    ("points_total", POINTS_RE, None),
    ("rebounds_total", REBOUNDS_RE, None),
    ("assists_total", ASSISTS_RE, None),
]


def normalize_market_label(
    market_label: str,
    selection_label: str,
    home_team: str,
    away_team: str,
) -> MarketMatch | None:
    """Tente une normalisation deterministe. Retourne None si aucune regle ne matche
    (fallback IA obligatoire), ou un MarketMatch avec confidence < 0.9 si ambigu.
    """
    label = f"{market_label} {selection_label}".strip()

    # --- BTTS : verifier avant "goals" (le mot "marquent" ne contient pas "but") ---
    if BTTS_RE.search(market_label):
        selection = _over_under_selection(selection_label) or _over_under_selection(market_label)
        if selection is None:
            return None
        return MarketMatch("btts", selection, 2, None, None, 0.97)

    # --- 1X2 (plein temps ou mi-temps) ---
    if RESULT_1X2_RE.search(market_label) and not HANDICAP_RE.search(market_label):
        selection = None
        if SELECTION_HOME_RE.search(selection_label):
            selection = "home"
        elif SELECTION_DRAW_RE.search(selection_label):
            selection = "draw"
        elif SELECTION_AWAY_RE.search(selection_label):
            selection = "away"
        if selection is None:
            return None
        market_type = "1x2" + _period_suffix(market_label)
        return MarketMatch(market_type, selection, 3, None, None, 0.98)

    # --- European/Asian handicap : structure ambigue -> confiance basse, IA tranche ---
    if HANDICAP_RE.search(market_label):
        return MarketMatch("handicap_ambiguous", "home", 3, _parse_line(label), None, 0.4)

    # --- Marches binaires Over/Under generiques (corners, tirs, buts, points...) ---
    for market_type, pattern, exclude in _BINARY_KEYWORDS:
        if not pattern.search(market_label):
            continue
        if exclude is not None and exclude.search(market_label):
            continue
        selection = _over_under_selection(selection_label)
        line = _parse_line(selection_label)
        if selection is None or line is None:
            return MarketMatch(market_type, "over", 2, line, None, 0.5)
        scope = _team_scope(market_label, home_team, away_team)
        resolved_type = market_type.replace("_total", "_team") if scope else market_type
        resolved_type += _period_suffix(market_label)
        return MarketMatch(resolved_type, selection, 2, line, scope, 0.95)

    return None
