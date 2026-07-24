"""Service de collecte continue, une tache asyncio independante par bookmaker.

Chaque bookmaker a sa propre cadence (30 s pre-match / 10 s live, spec MISSION
§3) et sa propre sante : la panne d'un book n'interrompt pas les autres, et une
indisponibilite > 5 min declenche une alerte (spec MISSION §9).

Le collector ne fait que **produire** des cotes dans le pool ; la detection
d'arbitrage est consommatrice et vit dans main.py. Ce decouplage permet de
scraper a des rythmes differents de ceux de l'evaluation.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol

from ..normalizer.schema import Odd
from ..scrapers.base import ScraperUnavailableError
from .pool import OddsPool

logger = logging.getLogger("surebet.collector")


class SupportsScrape(Protocol):
    bookmaker_name: str

    async def scrape(self, sport: str) -> list[Odd]: ...


@dataclass(slots=True)
class BookmakerHealth:
    bookmaker: str
    last_success: datetime | None = None
    last_failure: datetime | None = None
    consecutive_failures: int = 0
    total_cycles: int = 0
    total_odds: int = 0
    alerted_unavailable: bool = False

    @property
    def seconds_since_success(self) -> float | None:
        if self.last_success is None:
            return None
        return (datetime.now(timezone.utc) - self.last_success).total_seconds()

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures == 0


@dataclass(slots=True)
class CollectorTask:
    """Un bookmaker + sa cadence de rafraichissement."""

    scraper: SupportsScrape
    interval_s: float
    sport: str = "football"
    health: BookmakerHealth = field(init=False)

    def __post_init__(self) -> None:
        self.health = BookmakerHealth(bookmaker=self.scraper.bookmaker_name)


class Collector:
    def __init__(
        self,
        pool: OddsPool,
        tasks: list[CollectorTask],
        unavailable_alert_after_s: float = 300.0,
        on_unavailable: Callable[[BookmakerHealth], Awaitable[None]] | None = None,
        jitter_s: float = 0.0,
    ) -> None:
        self.pool = pool
        self.tasks = tasks
        self.unavailable_alert_after_s = unavailable_alert_after_s
        self.on_unavailable = on_unavailable
        self.jitter_s = jitter_s
        self._running: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    @property
    def health(self) -> list[BookmakerHealth]:
        return [t.health for t in self.tasks]

    async def collect_once(self, task: CollectorTask) -> int:
        """Un cycle de collecte pour un bookmaker. Retourne le nombre de cotes."""
        health = task.health
        health.total_cycles += 1
        try:
            odds = await task.scraper.scrape(task.sport)
        except ScraperUnavailableError as exc:
            self._record_failure(health, str(exc))
            await self._maybe_alert(health)
            return 0
        except Exception as exc:  # tout scraper defaillant reste isole
            logger.exception("%s: erreur inattendue de collecte", health.bookmaker)
            self._record_failure(health, str(exc))
            await self._maybe_alert(health)
            return 0

        await self.pool.update(health.bookmaker, odds)
        health.last_success = datetime.now(timezone.utc)
        health.consecutive_failures = 0
        health.total_odds += len(odds)
        if health.alerted_unavailable:
            logger.info("%s: retabli", health.bookmaker)
            health.alerted_unavailable = False
        logger.info("%s: %d cotes collectees", health.bookmaker, len(odds))
        return len(odds)

    def _record_failure(self, health: BookmakerHealth, reason: str) -> None:
        health.last_failure = datetime.now(timezone.utc)
        health.consecutive_failures += 1
        logger.error("%s: echec de collecte (#%d) - %s",
                     health.bookmaker, health.consecutive_failures, reason)

    async def _maybe_alert(self, health: BookmakerHealth) -> None:
        """Alerte si le bookmaker est muet depuis plus du seuil (spec MISSION §9)."""
        elapsed = health.seconds_since_success
        never_succeeded = health.last_success is None and health.consecutive_failures >= 3
        too_long = elapsed is not None and elapsed > self.unavailable_alert_after_s
        if (never_succeeded or too_long) and not health.alerted_unavailable:
            health.alerted_unavailable = True
            logger.critical(
                "ALERTE: %s indisponible (%s)",
                health.bookmaker,
                f"{elapsed:.0f}s sans succes" if elapsed is not None else
                f"{health.consecutive_failures} echecs consecutifs",
            )
            if self.on_unavailable is not None:
                await self.on_unavailable(health)

    async def _run_task_loop(self, task: CollectorTask) -> None:
        if self.jitter_s:
            await asyncio.sleep(random.uniform(0, self.jitter_s))
        while not self._stop.is_set():
            await self.collect_once(task)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=task.interval_s)
            except asyncio.TimeoutError:
                pass

    async def start(self) -> None:
        self._stop.clear()
        self._running = [asyncio.create_task(self._run_task_loop(t)) for t in self.tasks]
        logger.info("Collector demarre : %d bookmaker(s)", len(self.tasks))

    async def stop(self) -> None:
        self._stop.set()
        for t in self._running:
            t.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)
        self._running = []
        logger.info("Collector arrete")

    async def run_forever(self) -> None:
        await self.start()
        try:
            await asyncio.gather(*self._running)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
