"""Session navigateur persistante (une par bookmaker).

Motivation (issue du test live juillet 2026) : lancer/fermer un navigateur a
chaque scrape fait re-presenter le challenge Cloudflare a chaque cycle, ce qui
est lent et se fait bloquer. On maintient donc :

- un contexte navigateur **unique et durable** par bookmaker,
- un **profil persistant sur disque** (`user_data_dir`) pour que le cookie
  `cf_clearance` et la session survivent aux redemarrages du process,
- un mode `headless` configurable : le test live a montre qu'en headless
  Cloudflare bloque `/service-api/` (403) meme sur les requetes natives du site.
  En production, `headless=False` (avec affichage reel ou `xvfb-run` sous Linux)
  est le mode recommande.

La page est reutilisee entre les cycles : on ne fait que re-naviguer, ce qui
preserve le contexte anti-bot et divise le cout par cycle.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from ..scrapers.base import USER_AGENTS, ScraperUnavailableError

logger = logging.getLogger("surebet.collector.session")

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]


class BrowserSession:
    """Contexte navigateur durable, reutilise sur toute la duree de vie du collector."""

    def __init__(
        self,
        name: str,
        headless: bool = True,
        profile_dir: str | Path | None = None,
        locale: str = "fr-FR",
        user_agent: str | None = None,
        nav_timeout_ms: int = 30000,
    ) -> None:
        self.name = name
        self.headless = headless
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.locale = locale
        self.user_agent = user_agent or random.choice(USER_AGENTS)
        self.nav_timeout_ms = nav_timeout_ms

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self.started_at: datetime | None = None
        self.navigations = 0

    @property
    def is_started(self) -> bool:
        return self._context is not None

    async def start(self) -> None:
        if self.is_started:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise ScraperUnavailableError(
                "Playwright non installe. pip install playwright && playwright install chromium"
            ) from exc

        self._pw = await async_playwright().start()
        if self.profile_dir is not None:
            # Profil persistant : conserve cookies/cf_clearance entre les runs.
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = await self._pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                args=STEALTH_ARGS,
                locale=self.locale,
                user_agent=self.user_agent,
            )
        else:
            self._browser = await self._pw.chromium.launch(headless=self.headless, args=STEALTH_ARGS)
            self._context = await self._browser.new_context(locale=self.locale, user_agent=self.user_agent)

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self.started_at = datetime.now(timezone.utc)
        logger.info("Session navigateur demarree (%s, headless=%s, profil=%s)",
                    self.name, self.headless, self.profile_dir or "ephemere")

    async def stop(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._pw is not None:
                await self._pw.stop()
            self._pw = self._browser = self._context = self._page = None
            logger.info("Session navigateur arretee (%s)", self.name)

    async def __aenter__(self) -> "BrowserSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def render(self, url: str, wait_selector: str | None = None, timeout_ms: int | None = None) -> str:
        """Navigue et renvoie le HTML rendu, en reutilisant la page existante."""
        if not self.is_started:
            await self.start()
        timeout = timeout_ms or self.nav_timeout_ms
        await self._page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        await self.wait_cloudflare_clear()
        if wait_selector:
            try:
                await self._page.wait_for_selector(wait_selector, timeout=timeout)
            except Exception:
                logger.warning("%s: selecteur %r absent sur %s", self.name, wait_selector, url)
        self.navigations += 1
        return await self._page.content()

    async def wait_cloudflare_clear(self, timeout_s: float = 20.0) -> bool:
        """Attend la resolution du challenge Cloudflare ("Just a moment...")."""
        import asyncio

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            try:
                title = (await self._page.title()) or ""
            except Exception:
                return False
            if "moment" not in title.lower():
                return True
            await asyncio.sleep(1.0)
        logger.warning("%s: challenge Cloudflare non resolu dans le delai", self.name)
        return False

    async def capture_json(self, page_url: str, url_fragment: str, wait_s: float = 12.0) -> dict | None:
        """Charge `page_url` et intercepte la reponse JSON du site dont l'URL
        contient `url_fragment`.

        C'est la strategie validee en test live : plutot que d'emettre notre
        propre requete (que Cloudflare challenge separement), on laisse le site
        faire son appel natif et on lit la reponse.
        """
        import asyncio

        if not self.is_started:
            await self.start()
        captured: dict = {}

        async def on_response(resp):
            if url_fragment in resp.url and resp.status == 200 and "payload" not in captured:
                try:
                    captured["payload"] = await resp.json()
                except Exception:
                    pass

        self._page.on("response", on_response)
        try:
            await self._page.goto(page_url, timeout=self.nav_timeout_ms, wait_until="domcontentloaded")
            await self.wait_cloudflare_clear()
            loop = asyncio.get_event_loop()
            deadline = loop.time() + wait_s
            while loop.time() < deadline and "payload" not in captured:
                await asyncio.sleep(0.5)
        finally:
            self._page.remove_listener("response", on_response)
        return captured.get("payload")
