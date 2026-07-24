"""Scraper 1xBet Haiti - API JSON LineFeed (spec MISSION §1).

Utilise l'API LineFeed (Get1x2_VZip). Les champs E[].G (group id) et E[].T
(type id) suivent les conventions 1xbet communement observees.

TEST LIVE (juillet 2026) - findings confirmes en interrogeant ht.1xbet.com :
- La route correcte est `/service-api/LineFeed/Get1x2_VZip` : sans le prefixe
  `/service-api/`, le domaine Haiti repond 404 "Fail route".
- Le parametre de sport est `sports=` (pas `sportId=`).
- **L'API est desormais frontee par Cloudflare** : un GET httpx direct recoit un
  403 "Just a moment..." (challenge JS). La mission supposait un acces JSON
  simple ; ce n'est plus le cas. On tente donc httpx d'abord (fonctionne depuis
  certaines regions/IP ou si le challenge est absent), puis on retombe sur un
  fetch via navigateur Playwright qui resout le challenge et lit le JSON rendu.
"""
from __future__ import annotations

import json
import logging
import random
from asyncio import sleep as _asyncio_sleep
from datetime import datetime, timezone

from ..normalizer.schema import Odd, make_match_id
from .base import USER_AGENTS, BookmakerScraper, ScraperUnavailableError

logger = logging.getLogger("surebet.scrapers.xbet")

# Conventions 1xbet publiques (a recalibrer en prod si necessaire)
SPORT_IDS = {"football": 1, "basketball": 4}
GROUP_1X2 = 1
GROUP_TOTALS = 17  # Total buts/points match entier, T=9 -> over, T=10 -> under
TOTAL_OVER_T = 9
TOTAL_UNDER_T = 10


class XBetScraper(BookmakerScraper):
    bookmaker_name = "1xBet"

    # En-tete custom emis par le front 1xBet, identifie en test live sur les
    # requetes reelles du site vers /service-api/* (necessaire cote feed).
    SVC_SOURCE_HEADER = "__V3_HOST_APP__"

    def __init__(
        self,
        base_url: str = "https://ht.1xbet.com",
        use_browser_fallback: bool = True,
        headless: bool = True,
        sport_line_path: str = "/fr/line/football",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.use_browser_fallback = use_browser_fallback
        # TEST LIVE : en mode headless, Cloudflare bloque /service-api/ (403), y
        # compris les propres requetes du site. Un navigateur NON-headless
        # (headless=False) passe generalement le challenge. A activer en prod
        # via un environnement disposant d'un affichage (ou xvfb sous Linux).
        self.headless = headless
        self.sport_line_path = sport_line_path

    def _event_url(self, sport_id: int, count: int = 50) -> str:
        # Route confirmee en test live : prefixe /service-api/ + parametre sports=
        return (
            f"{self.base_url}/service-api/LineFeed/Get1x2_VZip"
            f"?sports={sport_id}&count={count}&lng=fr&mode=4&country=71&partner=1&getEmpty=true"
        )

    async def _fetch_payload(self, url: str) -> dict:
        """httpx d'abord ; repli navigateur si Cloudflare challenge (403/HTML)."""
        try:
            return await self.fetch_json(url)
        except ScraperUnavailableError:
            if not self.use_browser_fallback:
                raise
            logger.warning("1xBet: httpx bloque (Cloudflare), repli sur Playwright")
            return await self._fetch_payload_browser(url)

    async def _fetch_payload_browser(self, url: str) -> dict:
        """Recupere le JSON du feed via navigateur en contournant Cloudflare.

        Strategie (issue du test live juillet 2026) : plutot que de refaire un
        fetch() manuel (que Cloudflare re-challenge separement sur /service-api/),
        on charge la page sportive et on **intercepte la propre reponse du site**
        a Get1x2_VZip, qui porte le contexte Cloudflare valide. On declenche aussi
        un fetch() de secours avec les en-tetes reels (x-svc-source) si le site ne
        rejoue pas la requete. En headless, Cloudflare bloque toujours (403) :
        headless=False est requis en prod (voir __init__).
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise ScraperUnavailableError(
                "Playwright requis pour contourner Cloudflare sur 1xBet. "
                "pip install playwright && playwright install chromium"
            ) from exc

        intercepted: dict = {}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless, args=["--disable-blink-features=AutomationControlled"]
            )
            try:
                context = await browser.new_context(user_agent=random.choice(USER_AGENTS), locale="fr-FR")
                page = await context.new_page()

                async def on_response(resp):
                    if "Get1x2_VZip" in resp.url and resp.status == 200 and "payload" not in intercepted:
                        try:
                            intercepted["payload"] = await resp.json()
                        except Exception:
                            pass

                page.on("response", on_response)
                await self._jitter_delay()
                await page.goto(self.base_url + self.sport_line_path, timeout=45000, wait_until="domcontentloaded")
                await self._wait_cloudflare_clear(page)

                # Laisse le site charger ses propres feeds (intercepte ci-dessus)
                for _ in range(12):
                    if "payload" in intercepted:
                        break
                    await _asyncio_sleep(1.0)

                if "payload" not in intercepted:
                    # Secours : fetch in-page avec les en-tetes reels du front
                    body = await page.evaluate(
                        """async (args) => {
                            const [u, svc] = args;
                            const r = await fetch(u, {
                                headers: {
                                    'Accept': 'application/json, text/plain',
                                    'x-requested-with': 'XMLHttpRequest',
                                    'x-svc-source': svc
                                },
                                credentials: 'include'
                            });
                            return await r.text();
                        }""",
                        [url, self.SVC_SOURCE_HEADER],
                    )
                    intercepted["payload"] = json.loads(body)

                self.last_success_at = datetime.now(timezone.utc)
                return intercepted["payload"]
            except json.JSONDecodeError as exc:
                raise ScraperUnavailableError(
                    "1xBet: feed non-JSON via navigateur (Cloudflare non franchi en headless ; "
                    "utiliser headless=False en prod)"
                ) from exc
            except Exception as exc:
                raise ScraperUnavailableError(f"1xBet: echec navigateur ({exc})") from exc
            finally:
                await browser.close()

    @staticmethod
    async def _wait_cloudflare_clear(page, timeout_ms: int = 20000) -> None:
        """Attend que le challenge Cloudflare ("Just a moment...") se resolve."""
        import asyncio as _asyncio

        deadline = _asyncio.get_event_loop().time() + timeout_ms / 1000
        while _asyncio.get_event_loop().time() < deadline:
            title = (await page.title()) or ""
            if "moment" not in title.lower():
                return
            await _asyncio.sleep(1.0)
        logger.warning("1xBet: challenge Cloudflare non resolu dans le delai imparti")

    async def scrape(self, sport: str) -> list[Odd]:
        sport_id = SPORT_IDS.get(sport)
        if sport_id is None:
            raise ValueError(f"Sport non supporte par le scraper 1xBet: {sport!r}")

        payload = await self._fetch_payload(self._event_url(sport_id))
        events = payload.get("Value") or []

        odds: list[Odd] = []
        scraped_at = datetime.now(timezone.utc)
        for event in events:
            try:
                odds.extend(self._parse_event(event, sport, scraped_at))
            except Exception:
                logger.exception("Evenement 1xBet illisible, ignore: %r", event.get("I"))
        return odds

    def _parse_event(self, event: dict, sport: str, scraped_at: datetime) -> list[Odd]:
        match_id_raw = event.get("I")
        home_team = event.get("O1")
        away_team = event.get("O2")
        league = event.get("L", "")
        start_ts = event.get("S")
        entries = event.get("E") or []

        if not home_team or not away_team or start_ts is None:
            return []

        start_time = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        match_id = make_match_id(home_team, away_team, start_time)
        url = f"{self.base_url}/line/football/{match_id_raw}" if sport == "football" else f"{self.base_url}/line/basketball/{match_id_raw}"

        results: list[Odd] = []

        for entry in entries:
            group = entry.get("G")
            outcome_type = entry.get("T")
            coefficient = entry.get("C")
            line_param = entry.get("P")

            if coefficient is None or coefficient <= 1.0:
                continue

            if group == GROUP_1X2 and outcome_type in (1, 2, 3):
                selection = {1: "home", 2: "draw", 3: "away"}[outcome_type]
                results.append(
                    Odd(
                        bookmaker=self.bookmaker_name,
                        sport=sport,
                        competition=league,
                        match_id=match_id,
                        home_team=home_team,
                        away_team=away_team,
                        start_time=start_time,
                        market_type="1x2",
                        n_outcomes=3,
                        selection=selection,
                        line=None,
                        team_scope=None,
                        odds=float(coefficient),
                        url=url,
                        scraped_at=scraped_at,
                    )
                )
            elif group == GROUP_TOTALS and outcome_type in (TOTAL_OVER_T, TOTAL_UNDER_T) and line_param is not None:
                selection = "over" if outcome_type == TOTAL_OVER_T else "under"
                market_type = "goals_total" if sport == "football" else "points_total"
                results.append(
                    Odd(
                        bookmaker=self.bookmaker_name,
                        sport=sport,
                        competition=league,
                        match_id=match_id,
                        home_team=home_team,
                        away_team=away_team,
                        start_time=start_time,
                        market_type=market_type,
                        n_outcomes=2,
                        selection=selection,
                        line=float(line_param),
                        team_scope=None,
                        odds=float(coefficient),
                        url=url,
                        scraped_at=scraped_at,
                    )
                )
        return results
