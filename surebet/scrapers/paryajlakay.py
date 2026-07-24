"""Scraper Paryaj Lakay (spec MISSION §1) - SPA Angular, Playwright.

Structure reelle (recon juillet 2026) : page evenement rendue cote client,
marches en blocs `div.bet-type` (titre `.bet-type-infos`) suivis de
`hg-event-bet-type-item` (`.name` = selection, `.odds` = cote en virgule
decimale). Extraction dans parsing.extract_markets_from_html.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from ..normalizer.schema import Odd
from .parsing import MatchMeta
from .playwright_base import PlaywrightScraper

logger = logging.getLogger("surebet.scrapers.paryajlakay")

EVENT_LINK_RE = re.compile(r"/sports/event/[a-z0-9\-]+m\d+", re.I)


class ParyajLakayScraper(PlaywrightScraper):
    bookmaker_name = "Paryaj Lakay"

    SPORT_PATHS = {"football": "/sports", "basketball": "/sports"}
    ITEM_SELECTOR = "hg-event-bet-type-item"

    def __init__(self, base_url: str = "https://www.paryajlakay.com", **kwargs) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")

    # Libelle du sport dans le menu lateral : le deployer double le nombre
    # d'evenements listes (10 -> 20 en test live).
    SPORT_MENU_LABEL = {"football": "Football", "basketball": "Basketball"}

    async def _list_event_urls(self, sport: str, limit: int = 60) -> list[str]:
        """Collecte les URLs d'evenements depuis la page listing du sport.

        La page n'affiche qu'une poignee de matchs vedettes ; les competitions
        du menu lateral ne sont pas des liens <a> mais des elements cliquables.
        On deploie donc le sport puis on parcourt les competitions en cliquant,
        en accumulant les URLs a chaque etape (voir _harvest_via_clicks).
        """
        listing = f"{self.base_url}{self.SPORT_PATHS.get(sport, '/sports')}"
        html = await self._render_html(listing, wait_selector="a[href*='/sports/event/']")
        urls = self._urls_from_html(html)

        if self.session is not None and self.session.page is not None:
            urls |= await self._harvest_via_clicks(sport)

        return sorted(urls)[:limit]

    def _urls_from_html(self, html: str) -> set[str]:
        return {
            self.base_url + h if h.startswith("/") else h
            for h in EVENT_LINK_RE.findall(html)
        }

    async def _harvest_via_clicks(self, sport: str) -> set[str]:
        """Deploie le sport puis chaque competition, en recoltant les evenements.

        Sans navigateur pilotable (pas de session injectee), cette etape est
        simplement sautee et on se contente des matchs vedettes.
        """
        page = self.session.page
        collected: set[str] = set()
        label = self.SPORT_MENU_LABEL.get(sport, "Football")

        async def harvest() -> None:
            collected.update(self._urls_from_html(await page.content()))

        try:
            await page.evaluate(
                """(label) => {
                    const el = [...document.querySelectorAll('*')].find(
                        e => e.children.length === 0 &&
                             new RegExp('^' + label + '$', 'i').test((e.textContent||'').trim()));
                    if (el) el.click();
                }""",
                label,
            )
            await page.wait_for_timeout(2500)
            await harvest()

            competitions = await page.evaluate(
                """() => [...document.querySelectorAll('*')]
                    .filter(e => e.children.length === 0 &&
                                 /^(D\\d|Ligue|Liga|Serie|Premier|Copa|Coupe|Championship|MLS|Eliteserien|Allsvenskan)/i
                                   .test((e.textContent||'').trim()))
                    .map(e => (e.textContent||'').trim())
                    .filter((v, i, a) => a.indexOf(v) === i)
                    .slice(0, 12)"""
            )
            for name in competitions:
                try:
                    await page.evaluate(
                        """(name) => {
                            const el = [...document.querySelectorAll('*')].find(
                                e => e.children.length === 0 && (e.textContent||'').trim() === name);
                            if (el) el.click();
                        }""",
                        name,
                    )
                    await page.wait_for_timeout(1800)
                    await harvest()
                except Exception:
                    logger.debug("Paryaj Lakay: competition %r non deployable", name)
        except Exception:
            logger.warning("Paryaj Lakay: recolte par clics interrompue", exc_info=True)

        return collected

    async def _scrape_event(self, url: str, sport: str) -> list[Odd]:
        html = await self._render_html(url, wait_selector=self.ITEM_SELECTOR)
        markets = self._markets_from_html(html)
        meta = self._extract_meta(html, url, sport)
        if meta is None:
            logger.warning("Paryaj Lakay: metadonnees de match introuvables sur %s", url)
            return []
        return self._convert(markets, meta)

    def _extract_meta(self, html: str, url: str, sport: str) -> MatchMeta | None:
        """Extrait equipes/competition/heure. Selecteurs a affiner en prod si le
        markup evolue ; fallback sur le slug d'URL pour les noms d'equipes.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # Nom du match : element .name / hg-event categories dans la recon
        home = away = None
        name_el = soup.select_one(".informations .name, hg-event .name")
        if name_el:
            text = name_el.get_text(" ", strip=True)
            if " - " in text:
                home, away = (t.strip() for t in text.split(" - ", 1))
        if not home or not away:
            home, away = self._teams_from_slug(url)
        if not home or not away:
            return None

        comp_el = soup.select_one("hg-event-categories, .categories")
        competition = comp_el.get_text(" ", strip=True) if comp_el else ""

        return MatchMeta(
            bookmaker=self.bookmaker_name,
            sport=sport,
            competition=competition,
            home_team=home,
            away_team=away,
            start_time=self._extract_start_time(soup),
            url=url,
        )

    @staticmethod
    def _teams_from_slug(url: str) -> tuple[str | None, str | None]:
        # /sports/event/club-bolivar-gremio-porto-alegrense-rs-m76289162
        slug = url.rstrip("/").split("/")[-1]
        slug = re.sub(r"-m\d+$", "", slug)
        # heuristique faible : le slug ne delimite pas proprement les 2 equipes,
        # d'ou la priorite au markup ci-dessus. Retourne (None, None) si incertain.
        return None, None

    @staticmethod
    def _extract_start_time(soup) -> datetime:
        """Heure de debut du match depuis le DOM ("Aujourd'hui 18:00", "24/07 18:00").

        IMPORTANT : `match_id` est un hash (equipes + jour UTC). Retourner
        systematiquement l'heure courante ferait echouer l'appariement avec les
        autres bookmakers des qu'un match n'est pas le jour meme.
        """
        text = soup.get_text(" ", strip=True)[:2000]
        now = datetime.now(timezone.utc)

        time_match = re.search(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b", text)
        hour, minute = (int(time_match.group(1)), int(time_match.group(2))) if time_match else (0, 0)

        # Date explicite JJ/MM (eventuellement /AAAA)
        date_match = re.search(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b", text)
        if date_match:
            day, month = int(date_match.group(1)), int(date_match.group(2))
            year = int(date_match.group(3) or now.year)
            if year < 100:
                year += 2000
            try:
                return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            except ValueError:
                pass

        base = now
        if re.search(r"\bdemain\b|\btomorrow\b|\bdemen\b", text, re.I):
            base = now + timedelta(days=1)
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    async def scrape(self, sport: str) -> list[Odd]:
        all_odds: list[Odd] = []
        urls = await self._list_event_urls(sport)
        for url in urls:
            try:
                all_odds.extend(await self._scrape_event(url, sport))
            except Exception:
                logger.exception("Paryaj Lakay: echec sur l'evenement %s", url)
        return all_odds
