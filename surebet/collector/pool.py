"""Pool de cotes partage entre les collecteurs et le moteur de detection.

Chaque bookmaker publie son lot de cotes de facon atomique (remplacement complet
de sa contribution), et le moteur lit un instantane fusionne, filtre par
fraicheur (spec MISSION §9 : cotes de plus de 60 s ecartees).

Le decouplage est volontaire : le collector ne sait rien de l'arbitrage, et le
moteur ne sait pas comment les cotes ont ete obtenues (API, navigateur, fixture).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..normalizer.schema import Odd


@dataclass(slots=True)
class PoolStats:
    bookmaker: str
    count: int
    fresh_count: int
    last_update: datetime | None
    age_seconds: float | None


@dataclass(slots=True)
class _Entry:
    odds: list[Odd] = field(default_factory=list)
    updated_at: datetime | None = None


class OddsPool:
    """Instantane courant des cotes, une contribution par bookmaker.

    Sur `update()`, la contribution precedente du bookmaker est entierement
    remplacee : une cote retiree par le bookmaker disparait du pool au cycle
    suivant, ce qui evite de raisonner sur des lignes fermees.
    """

    def __init__(self, max_age_s: float = 60.0) -> None:
        self.max_age_s = max_age_s
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def update(self, bookmaker: str, odds: list[Odd]) -> None:
        async with self._lock:
            self._entries[bookmaker] = _Entry(odds=list(odds), updated_at=_now())

    async def snapshot(self, include_stale: bool = False) -> list[Odd]:
        """Cotes fusionnees de tous les bookmakers, fraiches par defaut."""
        async with self._lock:
            merged: list[Odd] = []
            for entry in self._entries.values():
                merged.extend(entry.odds)
        if include_stale:
            return merged
        return [o for o in merged if self._age(o) <= self.max_age_s]

    async def stats(self) -> list[PoolStats]:
        async with self._lock:
            items = list(self._entries.items())
        now = _now()
        out: list[PoolStats] = []
        for bookmaker, entry in items:
            fresh = sum(1 for o in entry.odds if self._age(o) <= self.max_age_s)
            age = (now - entry.updated_at).total_seconds() if entry.updated_at else None
            out.append(
                PoolStats(
                    bookmaker=bookmaker,
                    count=len(entry.odds),
                    fresh_count=fresh,
                    last_update=entry.updated_at,
                    age_seconds=age,
                )
            )
        return sorted(out, key=lambda s: s.bookmaker)

    async def clear(self, bookmaker: str | None = None) -> None:
        async with self._lock:
            if bookmaker is None:
                self._entries.clear()
            else:
                self._entries.pop(bookmaker, None)

    @property
    def bookmakers(self) -> list[str]:
        return sorted(self._entries)

    def _age(self, odd: Odd) -> float:
        return (_now() - odd.scraped_at.astimezone(timezone.utc)).total_seconds()


def _now() -> datetime:
    return datetime.now(timezone.utc)
