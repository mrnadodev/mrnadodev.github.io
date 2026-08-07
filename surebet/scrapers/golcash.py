"""Scraper Golcash Haiti (spec MISSION §1) - API BetConstruct "Swarm" (WebSocket).

TEST LIVE (juillet 2026) : Golcash tourne sur la plateforme BetConstruct. Sa
config publique `/conf.json` expose `socketUrl: wss://eu-swarm-newm.betconstruct.com/`
et `site_id: 1345`. Ce canal renvoie l'integralite des marches **sans Cloudflare,
sans navigateur et sans compte** — 44 matchs de football pre-match avec cotes 1X2
recuperes lors du test de validation.

C'est donc l'API qui est utilisee ici, et non le scraping DOM Playwright
initialement prevu : plus rapide, plus stable, sans dependance a un navigateur.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ..normalizer.schema import Odd, make_match_id
from .base import BookmakerScraper, ScraperUnavailableError
from .swarm import EVENT_TYPE_TO_SELECTION, SwarmClient, resolve_swarm_market

logger = logging.getLogger("surebet.scrapers.golcash")

SPORT_ALIASES = {"football": "Soccer", "basketball": "Basketball"}
GOLCASH_SITE_ID = 1345


class GolcashScraper(BookmakerScraper):
    bookmaker_name = "Golcash"

    def __init__(self, base_url: str = "https://www.golcashhaiti.com",
                 site_id: int = GOLCASH_SITE_ID, live: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.site_id = site_id
        self.live = live

    async def scrape(self, sport: str) -> list[Odd]:
        alias = SPORT_ALIASES.get(sport)
        if alias is None:
            raise ValueError(f"Sport non supporte par le scraper Golcash: {sport!r}")

        try:
            async with SwarmClient(site_id=self.site_id) as client:
                # market_types=None : on demande TOUS les marches, pas seulement
                # une liste blanche, pour capter ceux que l'operateur ajoute
                # (cartons, fautes, tirs... sur les grands matchs). La
                # reconnaissance se fait ensuite par resolve_swarm_market.
                data = await client.fetch_markets(
                    sport_alias=alias,
                    game_type=1 if self.live else 0,
                    market_types=None,
                )
        except Exception as exc:
            raise ScraperUnavailableError(f"Golcash (Swarm): {exc}") from exc

        odds = self._parse(data, sport)
        self.last_success_at = datetime.now(timezone.utc)
        logger.info("Golcash: %d cotes via Swarm (%s)", len(odds), sport)
        return odds

    def _parse(self, data: dict, sport: str) -> list[Odd]:
        scraped_at = datetime.now(timezone.utc)
        results: list[Odd] = []
        for sport_node in (data.get("sport") or {}).values():
            for competition in (sport_node.get("competition") or {}).values():
                name = competition.get("name", "")
                for game in (competition.get("game") or {}).values():
                    results.extend(self._parse_game(game, name, sport, scraped_at))
        return results

    def _parse_game(self, game: dict, competition: str, sport: str, scraped_at: datetime) -> list[Odd]:
        home = game.get("team1_name")
        away = game.get("team2_name")
        start_ts = game.get("start_ts")
        if not home or not away or not start_ts:
            return []

        start_time = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        match_id = make_match_id(home, away, start_time)
        url = f"{self.base_url}/fr/sports/event/{game.get('id')}"

        out: list[Odd] = []
        for market in (game.get("market") or {}).values():
            resolved = resolve_swarm_market(market.get("type"))
            if resolved is None:
                continue
            market_type, n_outcomes, team_scope = resolved

            for event in (market.get("event") or {}).values():
                selection = EVENT_TYPE_TO_SELECTION.get(event.get("type"))
                price = event.get("price")
                if selection is None or not price or float(price) <= 1.0:
                    continue
                try:
                    out.append(
                        Odd(
                            bookmaker=self.bookmaker_name, sport=sport, competition=competition,
                            match_id=match_id, home_team=home, away_team=away,
                            start_time=start_time, market_type=market_type, n_outcomes=n_outcomes,
                            selection=selection, line=_extract_line(event.get("name")),
                            team_scope=team_scope, odds=float(price), url=url, scraped_at=scraped_at,
                        )
                    )
                except ValueError:  # cote/selection invalide : ligne ignoree
                    continue
        return out


def _extract_line(name: str | None) -> float | None:
    """Extrait le seuil d'un libelle Swarm ("Over 2.5" -> 2.5)."""
    if not name:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", name)
    return float(match.group(1)) if match else None
