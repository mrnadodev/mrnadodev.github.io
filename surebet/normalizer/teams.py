"""Fuzzy matching des noms d'equipes entre bookmakers (spec MISSION §3, seuil 85)."""
from __future__ import annotations

import re
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


# Marqueurs d'equipes DISTINCTES portant le meme nom de club.
#
# Piege releve en test live : "Eltham Redbacks U-23" et "Eltham Redbacks"
# obtiennent un score de similarite de 88, au-dessus du seuil de 85 — mais ce
# sont deux matchs differents, joues a des heures differentes et cotes
# differemment. Les apparier fabriquait un faux surebet a +5,73 % de ROI.
#
# Deux libelles ne peuvent designer la meme equipe que s'ils portent le MEME
# marqueur (les deux U-23, ou aucun des deux).
SQUAD_MARKERS: dict[str, re.Pattern] = {
    "youth": re.compile(r"\bu-?\s?(?:15|16|17|18|19|20|21|22|23)\b|\byouth\b|\bjunior|\bjeunes?\b", re.I),
    "reserve": re.compile(r"\breserves?\b|\bres\.\b|\bII\b|\bB\b(?!\w)|\bacademy\b|\bacad[eé]mie\b", re.I),
    "women": re.compile(r"\b(?:women|feminin|f[eé]minines?|dames|ladies|\(w\)|\bw\b)\b", re.I),
}


def squad_marker(name: str) -> str | None:
    """Marqueur d'equipe (jeunes, reserve, feminine) ou None pour l'equipe premiere."""
    for marker, pattern in SQUAD_MARKERS.items():
        if pattern.search(name):
            return marker
    return None


def same_squad_level(name_a: str, name_b: str) -> bool:
    """True si les deux libelles designent le meme niveau d'equipe."""
    return squad_marker(name_a) == squad_marker(name_b)


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
    """True si deux libelles d'equipe (bookmakers differents) designent la meme equipe.

    Le niveau d'equipe (premiere / U-23 / reserve / feminine) est verifie AVANT
    la similarite : sans ce garde-fou, "Eltham Redbacks U-23" et
    "Eltham Redbacks" matchent a 88 et produisent un faux arbitrage.
    """
    if not same_squad_level(name_a, name_b):
        return False
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
    # Ne comparer qu'a des equipes de meme niveau (premiere / U-23 / reserve...)
    eligible = [c for c in candidates if same_squad_level(raw_name, c)]
    if not eligible:
        return None
    resolved = resolve_alias(raw_name)
    result = process.extractOne(resolved, eligible, scorer=fuzz.token_sort_ratio)
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
