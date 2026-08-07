"""Extraction des FunBets depuis le HTML de la page /sports/manual-odds-boosts.

Structure DOM reelle (Paryaj Lakay, juillet 2026), confirmee en live :
- `.manual-odds-boost` : un GROUPE par match, avec un lien
  `a[href*='/sports/event/']` dont le texte est le match ("UTA Arad - ...") ;
- a l'interieur, plusieurs `.manual-odds-with-event-item` (un par pari boost) :
  - `.odds-name` : la description ("Otelul reussit 8 tirs cadres ou + & ...") ;
  - `.value` : la cote boostee (parfois affichee en double -> on prend la 1re).

La conversion en conditions elementaires est deleguee a parser.parse_funbet.
"""
from __future__ import annotations

import re

from .parser import FunBet, parse_funbet

ODDS_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*$")
MATCH_RE = re.compile(r"[\w .'&/-]+ - [\w .'&/-]+")


def extract_funbets_from_html(html: str) -> list[FunBet]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    funbets: list[FunBet] = []

    for group in soup.select(".manual-odds-boost"):
        match_title, url = _match_of_group(group)
        items = group.select(".manual-odds-with-event-item")
        if not items:  # structure a plat : un seul pari dans le groupe
            items = [group]
        for item in items:
            name_el = item.select_one(".odds-name")
            if name_el is None:
                continue
            description = name_el.get_text(" ", strip=True)
            odds = _first_odds(item)
            if odds is None or not description:
                continue
            funbets.append(parse_funbet(match_title, description, odds, url))
    return funbets


def _match_of_group(group) -> tuple[str, str | None]:
    link = group.select_one("a[href*='/sports/event/']")
    if link is not None:
        text = link.get_text(" ", strip=True)
        if " - " in text:
            return text, link.get("href")
    # repli : premier texte "X - Y" du groupe
    m = MATCH_RE.search(group.get_text(" ", strip=True))
    href = link.get("href") if link is not None else None
    return (m.group(0).strip() if m else ""), href


def _first_odds(item) -> float | None:
    for val in item.select(".value, .odds"):
        text = val.get_text(" ", strip=True).replace(",", ".")
        if ODDS_RE.match(text):
            return float(text)
    return None
