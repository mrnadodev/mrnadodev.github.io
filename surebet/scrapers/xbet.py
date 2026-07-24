"""Scraper 1xBet Haiti (spec MISSION §1) - API JSON LineFeed via empreinte TLS Chrome.

TEST LIVE (juillet 2026) — comment le blocage a ete leve, sans navigateur ni frais :

Cloudflare protege `/service-api/` et renvoyait un 403 "Just a moment..." a
`httpx`, y compris depuis un Chromium headless piloté par Playwright (les
requetes natives du site echouaient aussi). Le facteur discriminant n'etait pas
le navigateur mais l'**empreinte TLS** : Cloudflare identifie le client par son
handshake (JA3), et la pile TLS de Python est immediatement reconnaissable.

`curl_cffi` avec `impersonate="chrome"` reproduit le handshake exact de Chrome :
Cloudflare laisse passer, et il ne reste que l'API elle-meme. Deux parametres
ont ensuite du etre cales sur le flux reel :

- route `/service-api/LineFeed/...` (sans le prefixe : 404 "Fail route")
- `sports=` (et non `sportId=`)
- **`partner=151`** — avec `partner=1`, l'API repond 406 NotAcceptableException
- en-tete `x-svc-source: __V3_HOST_APP__`, emis par le front 1xBet

Aucun navigateur, aucun proxy, aucun service payant.

Structure du flux : chaque evenement porte ses marches dans `E[]`, identifies
par un groupe `G` et un type `T`, avec `C` = cote et `P` = ligne. Les couples
(G, T) ci-dessous ont ete valides par coherence de marge sur 50 matchs reels.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ..normalizer.schema import Odd, make_match_id
from .base import BookmakerScraper, ScraperUnavailableError

logger = logging.getLogger("surebet.scrapers.xbet")

SPORT_IDS = {"football": 1, "basketball": 3}
XBET_PARTNER = 151
IMPERSONATE = "chrome"

# (G, T) -> (market_type, n_outcomes, selection, team_scope)
# Marges moyennes mesurees sur 50 matchs : G=1 9,4 % | G=17 8,1 % |
# G=15 8,3 % | G=62 8,5 % | G=19 8,8 %.
MARKET_MAP: dict[tuple[int, int], tuple[str, int, str, str | None]] = {
    (1, 1): ("1x2", 3, "home", None),
    (1, 2): ("1x2", 3, "draw", None),
    (1, 3): ("1x2", 3, "away", None),
    (17, 9): ("goals_total", 2, "over", None),
    (17, 10): ("goals_total", 2, "under", None),
    (15, 11): ("goals_team", 2, "over", "home"),
    (15, 12): ("goals_team", 2, "under", "home"),
    (62, 13): ("goals_team", 2, "over", "away"),
    (62, 14): ("goals_team", 2, "under", "away"),
    (19, 180): ("btts", 2, "over", None),
    (19, 181): ("btts", 2, "under", None),
}

# G=8 (Double Chance) est volontairement ABSENT : ses trois issues se
# recouvrent (1X / 12 / X2), d'ou une "marge" mesuree a 119 %. La traiter
# comme un marche a 3 issues fabriquerait des arbitrages fantomes.
EXCLUDED_GROUPS = {8}


class XBetScraper(BookmakerScraper):
    bookmaker_name = "1xBet"

    def __init__(self, base_url: str = "https://ht.1xbet.com", count: int = 100,
                 partner: int = XBET_PARTNER, language: str = "fr", **kwargs) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.count = count
        self.partner = partner
        self.language = language

    def _feed_url(self, sport_id: int) -> str:
        return (
            f"{self.base_url}/service-api/LineFeed/Get1x2_VZip"
            f"?sports={sport_id}&count={self.count}&lng={self.language}"
            f"&mode=4&country=71&partner={self.partner}&getEmpty=true"
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain",
            "Accept-Language": "fr-FR,fr;q=0.9,ht;q=0.8",
            "x-requested-with": "XMLHttpRequest",
            "x-svc-source": "__V3_HOST_APP__",
            "Referer": f"{self.base_url}/{self.language}/line/football",
        }

    async def scrape(self, sport: str) -> list[Odd]:
        sport_id = SPORT_IDS.get(sport)
        if sport_id is None:
            raise ValueError(f"Sport non supporte par le scraper 1xBet: {sport!r}")

        payload = await self._fetch(self._feed_url(sport_id))
        if not payload.get("Success", True):
            raise ScraperUnavailableError(f"1xBet: reponse en echec ({payload.get('Error')})")

        odds: list[Odd] = []
        scraped_at = datetime.now(timezone.utc)
        for event in payload.get("Value") or []:
            try:
                odds.extend(self._parse_event(event, sport, scraped_at))
            except Exception:
                logger.exception("1xBet: evenement illisible, ignore (I=%r)", event.get("I"))

        self.last_success_at = scraped_at
        logger.info("1xBet: %d cotes recuperees (%s)", len(odds), sport)
        return odds

    async def _fetch(self, url: str) -> dict:
        """GET avec empreinte TLS Chrome (curl_cffi), execute hors boucle asyncio."""
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError as exc:  # pragma: no cover
            raise ScraperUnavailableError(
                "curl_cffi requis pour franchir Cloudflare sur 1xBet (pip install curl_cffi)"
            ) from exc

        def _get():
            return cffi_requests.get(
                url, headers=self._headers(), impersonate=IMPERSONATE, timeout=self.timeout
            )

        await self._jitter_delay()
        try:
            response = await asyncio.to_thread(_get)
        except Exception as exc:
            raise ScraperUnavailableError(f"1xBet: echec reseau ({exc})") from exc

        if response.status_code != 200:
            snippet = response.text[:120].replace("\n", " ")
            raise ScraperUnavailableError(
                f"1xBet: HTTP {response.status_code} — {snippet}"
            )
        try:
            return response.json()
        except Exception as exc:
            raise ScraperUnavailableError("1xBet: reponse non-JSON") from exc

    def _parse_event(self, event: dict, sport: str, scraped_at: datetime) -> list[Odd]:
        home = event.get("O1")
        away = event.get("O2")
        start_ts = event.get("S")
        if not home or not away or not start_ts:
            return []

        start_time = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        match_id = make_match_id(home, away, start_time)
        competition = event.get("L", "")
        url = f"{self.base_url}/{self.language}/line/football/{event.get('I', '')}"

        out: list[Odd] = []
        for entry in event.get("E") or []:
            group, type_id = entry.get("G"), entry.get("T")
            if group in EXCLUDED_GROUPS:
                continue
            mapped = MARKET_MAP.get((group, type_id))
            if mapped is None:
                continue
            market_type, n_outcomes, selection, team_scope = mapped

            coefficient = entry.get("C")
            if not coefficient or float(coefficient) <= 1.0:
                continue

            line = entry.get("P")
            try:
                out.append(
                    Odd(
                        bookmaker=self.bookmaker_name, sport=sport, competition=competition,
                        match_id=match_id, home_team=home, away_team=away,
                        start_time=start_time, market_type=market_type,
                        n_outcomes=n_outcomes, selection=selection,
                        line=float(line) if line is not None else None,
                        team_scope=team_scope, odds=float(coefficient),
                        url=url, scraped_at=scraped_at,
                    )
                )
            except ValueError:  # cote/selection hors contrat : ligne ignoree
                continue
        return out
