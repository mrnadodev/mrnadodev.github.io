"""Parseur des libelles FunBet -> conditions elementaires.

Exemples reels (Paryaj Lakay, juillet 2026) :
- "Otelul reussit 8 tirs cadres ou + & obtient 8 corners ou +"
- "UTA Arad gagne & les deux equipes marquent & chaque equipe obtient 6 corners ou +"
- "FC Arges reussit 10 tirs cadres ou + & obtient 10 corners ou +"

Chaque libelle est un ET de conditions. On decoupe sur "&"/"et", puis on
reconnait chaque condition (victoire, BTTS, seuils de tirs/corners par equipe
ou globaux). Les conditions non reconnues sont conservees en `unknown=True`
pour que le pricing sache qu'il ne peut pas les evaluer (honnetete : on ne
price jamais ce qu'on ne comprend pas).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Nettoyage : retirer la source "(source: Opta)" etc.
SOURCE_RE = re.compile(r"\(source[^)]*\)", re.I)
SPLIT_RE = re.compile(r"\s*&\s*|\s+et\s+|\s+and\s+", re.I)

WIN_RE = re.compile(r"(.+?)\s+(?:gagne|remporte|wins?|l'emporte)\b", re.I)
BTTS_RE = re.compile(r"les?\s*deux\s*[ée]quipes?\s*marquent|both\s*teams?\s*to\s*score|\bbtts\b", re.I)

# "8 tirs cadres ou +" / "reussit 8 tirs cadres ou +"
THRESHOLD_RE = re.compile(
    r"(\d+)\s*(tirs?\s*cadr[ée]s?|tirs?|corners?|buts?|cartons?|fautes?|"
    r"shots?\s*on\s*target|shots?|goals?|cards?|fouls?)\s*(?:ou\s*\+|\+|ou\s*plus|or\s*more)?",
    re.I,
)

STAT_CANON = {
    "tir cadre": "shots_on_target", "tirs cadres": "shots_on_target",
    "shot on target": "shots_on_target", "shots on target": "shots_on_target",
    "tir": "shots", "tirs": "shots", "shot": "shots", "shots": "shots",
    "corner": "corners", "corners": "corners",
    "but": "goals", "buts": "goals", "goal": "goals", "goals": "goals",
    "carton": "cards", "cartons": "cards", "card": "cards", "cards": "cards",
    "faute": "fouls", "fautes": "fouls", "foul": "fouls", "fouls": "fouls",
}

# "chaque equipe" -> la condition s'applique aux deux equipes
EACH_TEAM_RE = re.compile(r"chaque\s*[ée]quipe|each\s*team", re.I)


@dataclass(slots=True)
class Condition:
    kind: str            # "win" | "btts" | "threshold" | "unknown"
    team: str | None = None      # nom d'equipe si condition d'equipe
    each_team: bool = False      # seuil s'appliquant aux deux equipes
    stat: str | None = None      # shots_on_target | corners | goals | ...
    line: float | None = None    # seuil (N ou + -> line N-0.5 en Over)
    raw: str = ""
    unknown: bool = False


@dataclass(slots=True)
class FunBet:
    match: str                   # "UTA Arad - ASC Otelul Galati"
    home_team: str | None
    away_team: str | None
    description: str
    boosted_odds: float
    event_url: str | None
    conditions: list[Condition] = field(default_factory=list)

    @property
    def is_parsable(self) -> bool:
        """True si toutes les conditions sont reconnues (pricing possible)."""
        return bool(self.conditions) and not any(c.unknown for c in self.conditions)


def _canon_stat(word: str) -> str | None:
    from ..normalizer.schema import _strip_accents

    return STAT_CANON.get(_strip_accents(word).strip().lower())


def _teams_from_match(match: str) -> tuple[str | None, str | None]:
    if " - " in match:
        h, _, a = match.partition(" - ")
        return h.strip() or None, a.strip() or None
    return None, None


def parse_condition(fragment: str, home: str | None, away: str | None) -> Condition:
    text = fragment.strip()
    low = text.lower()

    if BTTS_RE.search(text):
        return Condition(kind="btts", raw=text)

    # seuil de statistique (tirs/corners/...)
    m = THRESHOLD_RE.search(text)
    if m:
        n = int(m.group(1))
        stat = _canon_stat(m.group(2))
        each = bool(EACH_TEAM_RE.search(text))
        team = _team_in_fragment(text, home, away) if not each else None
        if stat:
            return Condition(kind="threshold", team=team, each_team=each,
                             stat=stat, line=n - 0.5, raw=text)

    # victoire d'une equipe
    wm = WIN_RE.search(text)
    if wm:
        team = _team_in_fragment(text, home, away) or wm.group(1).strip()
        return Condition(kind="win", team=team, raw=text)

    return Condition(kind="unknown", raw=text, unknown=True)


def _team_in_fragment(text: str, home: str | None, away: str | None) -> str | None:
    from ..normalizer.teams import team_scope_in_label

    scope = team_scope_in_label(text, home or "", away or "")
    if scope == "home":
        return home
    if scope == "away":
        return away
    return None


def parse_funbet(match: str, description: str, boosted_odds: float,
                 event_url: str | None = None) -> FunBet:
    home, away = _teams_from_match(match)
    clean = SOURCE_RE.sub("", description).strip()
    fragments = [f for f in SPLIT_RE.split(clean) if f.strip()]
    conditions = [parse_condition(f, home, away) for f in fragments]
    return FunBet(
        match=match, home_team=home, away_team=away, description=description,
        boosted_odds=boosted_odds, event_url=event_url, conditions=conditions,
    )
