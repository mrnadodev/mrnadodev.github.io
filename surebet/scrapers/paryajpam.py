"""Scraper Paryaj Pam (spec MISSION §1) - WebSocket de cotes, token public "demo".

TEST LIVE (juillet 2026) : le feed de cotes n'est pas l'API REST
`admin-prod.newfeed.paryajpam.com` (qui repond `Unknown account`), mais un
WebSocket dedie acceptant le token public `demo` — donc **sans compte, sans
navigateur et sans Cloudflare**. Le protocole a ete reconstitue en interceptant
les trames reelles du site (voir `scrapers/pamws.py`).

Le scraper Playwright initialement prevu est donc remplace par ce client
WebSocket : plus rapide, plus stable, et sans dependance a un navigateur.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..normalizer.schema import Odd, make_match_id
from .base import BookmakerScraper, ScraperUnavailableError
from .pamws import (
    MARKET_TYPE_BY_TP,
    TEAM_SCOPE_BY_TP,
    ParyajPamWSClient,
    parse_outcomes,
    period_suffix,
)

logger = logging.getLogger("surebet.scrapers.paryajpam")

# Cle de regroupement du flux : 1 = Football, 3 = Basketball
SPORT_IDS = {"football": 1, "basketball": 3}


class ParyajPamScraper(BookmakerScraper):
    bookmaker_name = "Paryaj Pam"

    # count=500 : l'arbitrage exige le catalogue LARGE, pas la selection "hot".
    # Test live : count=50 -> 50 matchs et AUCUN recouvrement avec Golcash ;
    # count=500 -> 494 matchs et 5 matchs communs exploitables.
    def __init__(self, base_url: str = "https://www.paryajpam.com",
                 count: int = 500, mcount: int = 10, **kwargs) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.count = count
        self.mcount = mcount

    async def scrape(self, sport: str) -> list[Odd]:
        sport_id = SPORT_IDS.get(sport)
        if sport_id is None:
            raise ValueError(f"Sport non supporte par le scraper Paryaj Pam: {sport!r}")

        try:
            async with ParyajPamWSClient() as client:
                data = await client.fetch_events(sport=-1, count=self.count, mcount=self.mcount)
        except Exception as exc:
            raise ScraperUnavailableError(f"Paryaj Pam (WebSocket): {exc}") from exc

        odds = self._parse(data, sport, sport_id)
        self.last_success_at = datetime.now(timezone.utc)
        logger.info("Paryaj Pam: %d cotes via WebSocket (%s)", len(odds), sport)
        return odds

    def _parse(self, data: dict, sport: str, sport_id: int) -> list[Odd]:
        """`data` est indexe par identifiant de sport, chaque valeur groupant des evenements."""
        scraped_at = datetime.now(timezone.utc)
        results: list[Odd] = []
        for group in data.get(str(sport_id)) or []:
            competition = group.get("trn") or group.get("ctn") or ""
            for event in group.get("events") or []:
                results.extend(self._parse_event(event, competition, sport, scraped_at))
        return results

    def _parse_event(self, event: dict, competition: str, sport: str,
                     scraped_at: datetime) -> list[Odd]:
        home, away = _split_teams(event)
        start_time = _parse_start(event.get("tm"))
        if not home or not away or start_time is None:
            return []

        match_id = make_match_id(home, away, start_time)
        url = f"{self.base_url}/en/sport/event/{event.get('id')}"

        out: list[Odd] = []
        for market in (event.get("mr") or {}).values():
            if not isinstance(market, dict):
                continue
            mapped = MARKET_TYPE_BY_TP.get(market.get("tp"))
            if mapped is None:
                continue
            # Periode inconnue -> on ecarte, plutot que de risquer d'apparier
            # une mi-temps avec un match entier (spec MISSION §6.1).
            suffix = period_suffix(market)
            if suffix is None:
                continue
            base_type, n_outcomes = mapped
            market_type = f"{base_type}{suffix}"
            team_scope = TEAM_SCOPE_BY_TP.get(market.get("tp"))

            for selection, odds_value, line in parse_outcomes(market):
                try:
                    out.append(
                        Odd(
                            bookmaker=self.bookmaker_name, sport=sport, competition=competition,
                            match_id=match_id, home_team=home, away_team=away,
                            start_time=start_time, market_type=market_type,
                            n_outcomes=n_outcomes, selection=selection, line=line,
                            team_scope=team_scope, odds=odds_value, url=url,
                            scraped_at=scraped_at,
                        )
                    )
                except ValueError:  # selection/cote hors contrat : ligne ignoree
                    continue
        return out


def _split_teams(event: dict) -> tuple[str | None, str | None]:
    """Noms d'equipes : `cms` si disponible, sinon decoupage de `nm` ("A - B")."""
    teams = event.get("cms")
    if isinstance(teams, list) and len(teams) == 2 and all(teams):
        return teams[0], teams[1]
    name = event.get("nm") or ""
    if " - " in name:
        home, _, away = name.partition(" - ")
        return home.strip() or None, away.strip() or None
    return None, None


def _parse_start(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
