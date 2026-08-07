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

# ── BASKETBALL ───────────────────────────────────────────────────────────
# Le vainqueur au basket est un marche a DEUX issues : il n'y a pas de nul,
# la prolongation departage. Traiter ce marche comme un 1X2 a trois issues
# ferait chercher un triplet qui n'existe pas, et aucune detection ne
# sortirait jamais sur le marche principal.
WINNER_2WAY_RE = re.compile(
    r"vainqueur|gagnant|winner|money\s*line|moneyline|\b12\b|kiles?\s*k[ap]\s*genyen",
    re.I,
)

# LE PIEGE A EVITER. Certains bookmakers proposent AUSSI un marche « temps
# reglementaire », ou le nul existe (3 issues) parce que la prolongation
# n'est pas comptee. Apparier une cote « prolongations comprises » avec une
# cote « temps reglementaire » donne un faux surebet PARFAIT : le calcul est
# juste, mais si le match part en prolongation on perd les deux paris.
#
# Les deux variantes recoivent donc des market_type differents, ce qui les
# empeche structurellement de se retrouver dans le meme groupe.
REGULAR_TIME_RE = re.compile(
    r"temps\s*r[ée]glementaire|regular\s*time|sans\s*prolongation|"
    r"hors\s*prolongation|excluding\s*overtime|without\s*ot\b",
    re.I,
)

# Variantes promotionnelles : EXCLUES de l'arbitrage.
#
# Releve en test live sur Paryaj Lakay, un meme match expose simultanement :
#   "Resultat du match", "Resultat du match 2UP",
#   "Resultat du match (rembourse si match nul)",
#   "Resultat du match (rembourse si CSKA Moscou gagne)"
# Tous ces titres matchent RESULT_1X2_RE et leurs selections matchent 1/X/2.
#
# On les rejette au lieu de leur donner un market_type commun : leurs regles de
# paiement different (remboursement conditionnel, gain anticipe...), donc elles
# ne sont equivalentes ni au 1X2 standard, ni entre elles — y compris d'un
# bookmaker a l'autre. Les regrouper reintroduirait le faux appariement.
PROMO_VARIANT_RE = re.compile(
    r"\b2\s*up\b|bore\s*draw|insurance|assurance|cashback|rembours", re.I
)

# Format "N ou +" / "N or more" (Paryaj Lakay) : seuil unilateral cote a la
# hausse. "5 ou +" = au moins 5 = Over 4.5. Capte aussi "N ou plus", "N+".
N_OR_MORE_RE = re.compile(r"(\d+)\s*(?:ou\s*\+|ou\s*plus|or\s*more|\+)\s*$", re.I)

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
    sport: str = "football",
) -> MarketMatch | None:
    """Tente une normalisation deterministe. Retourne None si aucune regle ne matche
    (fallback IA obligatoire), ou un MarketMatch avec confidence < 0.9 si ambigu.

    `sport` vaut « football » par defaut : le comportement existant est
    inchange tant qu'on ne le precise pas.
    """
    label = f"{market_label} {selection_label}".strip()

    # --- Variantes promotionnelles : exclues de l'arbitrage (voir PROMO_VARIANT_RE) ---
    if PROMO_VARIANT_RE.search(label):
        return None

    # --- Vainqueur au basket : DEUX issues, la prolongation departage ---
    if sport == "basketball" and not HANDICAP_RE.search(market_label):
        est_resultat = (WINNER_2WAY_RE.search(market_label)
                        or RESULT_1X2_RE.search(market_label))
        if est_resultat:
            reglementaire = bool(REGULAR_TIME_RE.search(market_label))
            selection = None
            if SELECTION_HOME_RE.search(selection_label):
                selection = "home"
            elif SELECTION_AWAY_RE.search(selection_label):
                selection = "away"
            elif SELECTION_DRAW_RE.search(selection_label):
                # Un nul n'existe qu'en temps reglementaire. Annonce ailleurs,
                # c'est que le libelle a ete mal compris : on refuse plutot
                # que de fabriquer une issue impossible.
                if not reglementaire:
                    return None
                selection = "draw"
            if selection is None:
                return None
            if reglementaire:
                # Trois issues, et un market_type distinct : cette variante ne
                # doit JAMAIS etre appariee avec celle qui inclut les
                # prolongations, sous peine de faux surebet parfait.
                return MarketMatch("bb_result_reg" + _period_suffix(market_label),
                                   selection, 3, None, None, 0.96)
            return MarketMatch("bb_moneyline" + _period_suffix(market_label),
                               selection, 2, None, None, 0.97)

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
        return MarketMatch("1x2" + _period_suffix(market_label), selection, 3, None, None, 0.98)

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
        # Format "N ou +" (Paryaj Lakay) : "5 ou +" -> Over 4.5
        n_or_more = N_OR_MORE_RE.search(selection_label)
        if n_or_more:
            selection = "over"
            line = int(n_or_more.group(1)) - 0.5
        if selection is None or line is None:
            return MarketMatch(market_type, "over", 2, line, None, 0.5)
        scope = _team_scope(market_label, home_team, away_team)
        resolved_type = market_type.replace("_total", "_team") if scope else market_type
        resolved_type += _period_suffix(market_label)
        return MarketMatch(resolved_type, selection, 2, line, scope, 0.95)

    return None
