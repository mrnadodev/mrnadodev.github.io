"""Base commune pour les scrapers Playwright (Paryaj Lakay, Paryaj Pam, Golcash).

Ces trois sites sont des SPA (Angular/React) sans API JSON de cotes exposee et,
pour deux d'entre eux, derriere Cloudflare. Le rendu cote client impose un
navigateur headless. La logique de conversion (title/selection -> Odd) reste
dans parsing.py, pure et testable ; ici on ne fait que piloter le navigateur.

NOTE PROD : Cloudflare peut presenter des challenges anti-bot. Les selecteurs
CSS refletent la structure observee en reconnaissance (juillet 2026) et
devront etre revalides periodiquement. Respecter robots.txt et les rate-limits
(delais 1-3s herites, spec MISSION §3/§9).
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from ..normalizer.schema import Odd
from .base import USER_AGENTS, BookmakerScraper, ScraperUnavailableError
from .parsing import MatchMeta, RawMarket, extract_markets_from_html, raw_markets_to_odds

logger = logging.getLogger("surebet.scrapers.playwright")


class PlaywrightScraper(BookmakerScraper):
    """Scraper base navigateur. Les sous-classes fournissent la navigation et
    l'extraction des RawMarket ; la conversion en Odd est mutualisee.

    Une `BrowserSession` persistante peut etre injectee (voir collector/) : dans
    ce cas la page est reutilisee d'un cycle a l'autre au lieu de relancer un
    navigateur a chaque scrape, ce qui preserve le contexte anti-bot Cloudflare
    et divise fortement le cout par cycle. Sans session injectee, on retombe sur
    un navigateur ephemere (pratique pour un scrape ponctuel ou les tests).
    """

    base_url: str = ""
    session = None  # BrowserSession | None, injectee par le collector

    def attach_session(self, session) -> None:
        """Branche une session navigateur persistante (collector/session.py)."""
        self.session = session

    async def _render_html(self, url: str, wait_selector: str, timeout_ms: int = 20000) -> str:
        """Renvoie le HTML rendu, via la session persistante si disponible."""
        if self.session is not None:
            html = await self.session.render(url, wait_selector, timeout_ms)
            self.last_success_at = datetime.now(timezone.utc)
            return html
        return await self._render_html_ephemeral(url, wait_selector, timeout_ms)

    async def _render_html_ephemeral(self, url: str, wait_selector: str, timeout_ms: int = 20000) -> str:
        """Navigateur jetable : un lancement par appel (mode sans collector)."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise ScraperUnavailableError(
                "Playwright non installe. Executer: pip install playwright && playwright install chromium"
            ) from exc

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    locale="fr-FR",
                )
                page = await context.new_page()
                await self._jitter_delay()
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:
                    logger.warning("%s: selecteur %r absent sur %s", self.bookmaker_name, wait_selector, url)
                html = await page.content()
                self.last_success_at = datetime.now(timezone.utc)
                return html
            finally:
                await browser.close()

    def _convert(self, markets: list[RawMarket], meta: MatchMeta) -> list[Odd]:
        return raw_markets_to_odds(markets, meta)

    @staticmethod
    def _markets_from_html(html: str) -> list[RawMarket]:
        return extract_markets_from_html(html)
