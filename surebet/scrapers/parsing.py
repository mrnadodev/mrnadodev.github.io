"""Conversion des marches bruts extraits du DOM -> cotes canoniques (Odd).

La logique d'extraction DOM (Playwright) et la logique de conversion sont
separees : cette derniere est pure Python, testable hors-ligne sur des
fixtures HTML reelles (voir tests/fixtures/), sans dependance reseau.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ..normalizer.markets import normalize_market_label
from ..normalizer.schema import Odd, make_match_id

logger = logging.getLogger("surebet.scrapers.parsing")


@dataclass(slots=True)
class RawSelection:
    label: str  # libelle brut de la selection ("1", "> 2.5", "Oui", "Anba 7.5"...)
    odds_text: str  # cote brute ("1,57", "13"...)


@dataclass(slots=True)
class RawMarket:
    title: str  # titre brut du marche ("Resultat du match", "Nombre de buts"...)
    selections: list[RawSelection]


@dataclass(slots=True)
class MatchMeta:
    bookmaker: str
    sport: str
    competition: str
    home_team: str
    away_team: str
    start_time: datetime
    url: str


def parse_odds_value(text: str) -> float | None:
    """Convertit une cote texte (virgule decimale FR) en float. None si illisible."""
    cleaned = text.strip().replace(" ", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 1.0 else None


def raw_markets_to_odds(markets: list[RawMarket], meta: MatchMeta) -> list[Odd]:
    """Applique le normalizer deterministe a chaque (titre, selection) -> Odd.

    Les libelles ambigus (confidence < 0.9) sont ignores ici : le fallback IA
    (ai_normalizer) est branche en amont par l'orchestrateur pour ces cas, hors
    du chemin critique. Cette fonction ne fait que la conversion deterministe.
    """
    match_id = make_match_id(meta.home_team, meta.away_team, meta.start_time)
    scraped_at = datetime.now(timezone.utc)
    odds: list[Odd] = []

    for market in markets:
        for sel in market.selections:
            odds_value = parse_odds_value(sel.odds_text)
            if odds_value is None:
                continue
            match = normalize_market_label(market.title, sel.label, meta.home_team, meta.away_team, meta.sport)
            if match is None or match.confidence < 0.9:
                continue
            try:
                odds.append(
                    Odd(
                        bookmaker=meta.bookmaker,
                        sport=meta.sport,
                        competition=meta.competition,
                        match_id=match_id,
                        home_team=meta.home_team,
                        away_team=meta.away_team,
                        start_time=meta.start_time,
                        market_type=match.market_type,
                        n_outcomes=match.n_outcomes,
                        selection=match.selection,
                        line=match.line,
                        team_scope=match.team_scope,
                        odds=odds_value,
                        url=meta.url,
                        scraped_at=scraped_at,
                    )
                )
            except ValueError:
                logger.debug("Cote rejetee (validation Odd): %s / %s", market.title, sel.label)
    return odds


def extract_markets_from_html(html: str) -> list[RawMarket]:
    """Extrait les RawMarket d'une page evenement Paryaj Lakay (structure hg-*).

    Structure reelle observee : chaque marche = un `.bet-type` (titre dans
    `.bet-type-infos`) suivi d'un bloc frere contenant les
    `hg-event-bet-type-item` (chacun : `.name` = selection, `.odds` = cote).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    markets: list[RawMarket] = []

    for bet_type in soup.select("div.bet-type"):
        title_el = bet_type.select_one(".bet-type-infos")
        if title_el is None:
            continue
        title = title_el.get_text(strip=True)

        group = bet_type.find_next_sibling()
        if group is None:
            continue
        selections: list[RawSelection] = []
        for item in group.select("hg-event-bet-type-item"):
            name_el = item.select_one(".name")
            odds_el = item.select_one(".odds")
            if name_el is None or odds_el is None:
                continue
            selections.append(
                RawSelection(label=name_el.get_text(strip=True), odds_text=odds_el.get_text(strip=True))
            )
        if selections:
            markets.append(RawMarket(title=title, selections=selections))
    return markets
