"""Seed de demonstration : detecte les surebets des fixtures et les persiste.

Utile pour peupler le dashboard en local (`python -m surebet.seed_demo`).
"""
from __future__ import annotations

import asyncio

from .ai.scorer import ScoringContext, score_opportunity
from .ai.scout import Scout
from .config import settings
from .main import _load_fixture_pool
from .storage.db import init_db, make_engine, make_session_factory
from .storage.repository import OpportunityRepository


async def seed() -> int:
    engine = make_engine(settings.database_url)
    await init_db(engine)
    repo = OpportunityRepository(make_session_factory(engine))
    scout = Scout(min_roi=1.0, bankroll=settings.default_bankroll)
    opportunities = scout.evaluate(_load_fixture_pool())
    for opp in opportunities:
        opp.score_ia = score_opportunity(opp, ScoringContext())
        opp.explanation = await scout.explain(opp)
        await repo.save(opp)
    await engine.dispose()
    return len(opportunities)


if __name__ == "__main__":
    count = asyncio.run(seed())
    print(f"{count} opportunite(s) seedee(s) dans {settings.database_url}")
