"""Fuzzy matching des noms d'equipes entre bookmakers (spec MISSION §3, seuil 85)."""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

DEFAULT_THRESHOLD = 85

# Alias connus (abreviations, sponsors, graphies FR/EN/creole) -> forme canonique.
# Alimente au fil de l'usage reel ; le fuzzy matching couvre le reste.
KNOWN_ALIASES: dict[str, str] = {
    "psg": "paris saint-germain",
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "real": "real madrid",
    "barca": "barcelona",
    "gremio": "gremio porto alegrense",
    "bolivar": "club bolivar",
}


def _canonical_key(name: str) -> str:
    return " ".join(name.strip().lower().split())


def resolve_alias(name: str) -> str:
    key = _canonical_key(name)
    return KNOWN_ALIASES.get(key, name)


@dataclass(slots=True)
class TeamMatch:
    candidate: str
    score: float


def teams_match(name_a: str, name_b: str, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """True si deux libelles d'equipe (bookmakers differents) designent la meme equipe."""
    a = resolve_alias(name_a)
    b = resolve_alias(name_b)
    score = fuzz.token_sort_ratio(_canonical_key(a), _canonical_key(b))
    return score >= threshold


def best_team_match(
    raw_name: str, candidates: list[str], threshold: int = DEFAULT_THRESHOLD
) -> TeamMatch | None:
    """Meilleure correspondance de `raw_name` parmi `candidates` (registre d'equipes connues)."""
    if not candidates:
        return None
    resolved = resolve_alias(raw_name)
    result = process.extractOne(
        resolved, candidates, scorer=fuzz.token_sort_ratio
    )
    if result is None:
        return None
    candidate, score, _ = result
    if score < threshold:
        return None
    return TeamMatch(candidate=candidate, score=score)


def team_scope_in_label(label: str, home_team: str, away_team: str, threshold: int = DEFAULT_THRESHOLD) -> str | None:
    """Detecte si `label` (ex: "Total de buts de {Equipe}") mentionne le domicile ou l'exterieur.

    Utilise partial_ratio car `label` contient du texte additionnel autour du nom
    d'equipe ("Total de buts de X"), contrairement a teams_match qui compare deux
    libelles d'equipe purs.
    """
    label_key = _canonical_key(resolve_alias(label))
    home_score = fuzz.partial_ratio(label_key, _canonical_key(resolve_alias(home_team)))
    away_score = fuzz.partial_ratio(label_key, _canonical_key(resolve_alias(away_team)))
    if home_score < threshold and away_score < threshold:
        return None
    return "home" if home_score >= away_score else "away"
