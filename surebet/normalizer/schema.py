"""Schema canonique des cotes et opportunites (spec MISSION §4)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

VALID_SELECTIONS = {"over", "under", "home", "draw", "away"}
VALID_TEAM_SCOPES = {None, "home", "away"}


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_team_name(name: str) -> str:
    """Forme canonique d'un nom d'equipe pour le hachage de match_id.

    Ne remplace pas le fuzzy matching de normalizer/teams.py : c'est une
    normalisation purement syntaxique (accents, casse, espaces) utilisee
    pour construire une cle stable, deterministe.
    """
    cleaned = _strip_accents(name).lower().strip()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def make_match_id(home_team: str, away_team: str, start_time: datetime) -> str:
    """Hash normalise equipe_dom+equipe_ext+date -> identifiant de match stable."""
    day = start_time.astimezone(timezone.utc).strftime("%Y-%m-%d")
    key = f"{normalize_team_name(home_team)}|{normalize_team_name(away_team)}|{day}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Odd:
    bookmaker: str
    sport: str  # "football" | "basketball"
    competition: str
    match_id: str
    home_team: str
    away_team: str
    start_time: datetime
    market_type: str  # "1x2", "corners_total", "shots_team", "tackles_total", "var", ...
    n_outcomes: int  # 2 ou 3
    selection: str  # "over"|"under"|"home"|"draw"|"away"
    line: float | None  # 2.5, 7.5, 29.5 ... (None pour 1X2)
    team_scope: str | None  # None | "home" | "away"
    odds: float
    url: str
    scraped_at: datetime

    def __post_init__(self) -> None:
        if self.n_outcomes not in (2, 3):
            raise ValueError(f"n_outcomes doit etre 2 ou 3, recu {self.n_outcomes}")
        if self.selection not in VALID_SELECTIONS:
            raise ValueError(f"selection invalide: {self.selection!r}")
        if self.team_scope not in VALID_TEAM_SCOPES:
            raise ValueError(f"team_scope invalide: {self.team_scope!r}")
        if self.odds <= 1.0:
            raise ValueError(f"odds doit etre > 1.0, recu {self.odds}")

    @property
    def is_stale(self) -> bool:
        """True si la cote a plus de 60s (contrainte §9)."""
        age = (datetime.now(timezone.utc) - self.scraped_at.astimezone(timezone.utc))
        return age.total_seconds() > 60


@dataclass(slots=True)
class Leg:
    """Une jambe d'une opportunite d'arbitrage : une cote choisie chez un bookmaker."""
    bookmaker: str
    selection: str
    odds: float
    url: str
    event_label: str
    stake: float = 0.0


@dataclass(slots=True)
class Opportunity:
    match_id: str
    sport: str
    match_label: str  # "Home - Away"
    match_date: datetime
    market_type: str
    line: float | None
    team_scope: str | None
    n_outcomes: int
    legs: list[Leg] = field(default_factory=list)
    margin: float = 0.0
    roi_pct: float = 0.0
    bankroll: float = 0.0
    profit: float = 0.0
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    score_ia: int | None = None
    explanation: str | None = None
    status: str = "detected"
