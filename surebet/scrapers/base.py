"""Classe abstraite BookmakerScraper (spec MISSION architecture §3).

Rotation User-Agent, delais aleatoires 1-3s, retry exponentiel, gestion de
session/cookies via httpx.AsyncClient persistant. Les scrapers concrets
(xbet.py en JSON direct, les autres en Playwright) heritent de cette classe.
"""
from __future__ import annotations

import abc
import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ..normalizer.schema import Odd

logger = logging.getLogger("surebet.scrapers")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]


class ScraperUnavailableError(Exception):
    """Leve apres epuisement des tentatives de retry (spec MISSION §9 : alerte si > 5 min)."""


class BookmakerScraper(abc.ABC):
    bookmaker_name: str

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, timeout: float = 15.0) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self.last_success_at: datetime | None = None
        self.last_failure_at: datetime | None = None

    async def __aenter__(self) -> "BookmakerScraper":
        self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "fr-FR,fr;q=0.9,ht;q=0.8,en;q=0.7",
        }

    @staticmethod
    async def _jitter_delay(min_s: float = 1.0, max_s: float = 3.0) -> None:
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def fetch_json(self, url: str, **kwargs) -> dict:
        return await self._request_with_retry(url, mode="json", **kwargs)

    async def fetch_text(self, url: str, **kwargs) -> str:
        return await self._request_with_retry(url, mode="text", **kwargs)

    async def _request_with_retry(self, url: str, mode: str, **kwargs):
        if self._client is None:
            raise RuntimeError("Utiliser le scraper via 'async with' pour initialiser le client httpx")

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                await self._jitter_delay()
                response = await self._client.get(url, headers=self._headers(), **kwargs)
                response.raise_for_status()
                self.last_success_at = datetime.now(timezone.utc)
                return response.json() if mode == "json" else response.text
            except (httpx.HTTPError,) as exc:
                last_exc = exc
                delay = self.base_delay * (2**attempt)
                logger.warning(
                    "%s: tentative %s/%s echouee (%s), nouvel essai dans %.1fs",
                    self.bookmaker_name,
                    attempt + 1,
                    self.max_retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        self.last_failure_at = datetime.now(timezone.utc)
        raise ScraperUnavailableError(
            f"{self.bookmaker_name} indisponible apres {self.max_retries} tentatives"
        ) from last_exc

    @property
    def seconds_since_last_success(self) -> float | None:
        if self.last_success_at is None:
            return None
        return (datetime.now(timezone.utc) - self.last_success_at).total_seconds()

    @abc.abstractmethod
    async def scrape(self, sport: str) -> list["Odd"]:
        """Retourne les cotes normalisees au schema canonique (Odd) pour `sport`."""
        raise NotImplementedError
