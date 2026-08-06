"""Tests du storage async (spec MISSION §8) sur SQLite en memoire."""
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from surebet.ai.scout import Scout
from surebet.normalizer.schema import Odd
from surebet.storage.db import init_db, make_engine, make_session_factory
from surebet.storage.repository import OpportunityRepository


def _odd(bookmaker, selection, odds):
    return Odd(
        bookmaker=bookmaker, sport="football", competition="Amical", match_id="m1",
        home_team="Ghana", away_team="Colombie",
        start_time=datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc),
        market_type="1x2", n_outcomes=3, selection=selection, line=None, team_scope=None,
        odds=odds, url=f"https://{bookmaker}.example/bet", scraped_at=datetime.now(timezone.utc),
    )


@pytest_asyncio.fixture
async def repo():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    factory = make_session_factory(engine)
    yield OpportunityRepository(factory)
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_and_list_three_way(repo):
    scout = Scout(bankroll=50_000.0)
    opp = scout.evaluate([
        _odd("Paryaj Lakay", "home", 3.55),
        _odd("1xBet", "draw", 3.90),
        _odd("Golcash", "away", 3.30),
    ])[0]
    opp.score_ia = 88
    opp.explanation = "test"

    new_id = await repo.save(opp)
    assert new_id > 0

    rows = await repo.list_recent()
    assert len(rows) == 1
    row = rows[0]
    assert row.n_issues == 3
    assert row.bookmaker_c is not None
    assert row.final_balance == pytest.approx(row.init_balance + row.profit)
    assert row.score_ia == 88


@pytest.mark.asyncio
async def test_two_way_leaves_c_columns_null(repo):
    from surebet.normalizer.schema import Odd as O

    scout = Scout(bankroll=50_000.0)
    pool = [
        O(bookmaker="Paryaj Pam", sport="football", competition="", match_id="m2",
          home_team="Ghana", away_team="Colombie",
          start_time=datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc),
          market_type="shots_team", n_outcomes=2, selection="under", line=7.5, team_scope="home",
          odds=2.16, url="https://pam.example", scraped_at=datetime.now(timezone.utc)),
        O(bookmaker="Golcash", sport="football", competition="", match_id="m2",
          home_team="Ghana", away_team="Colombie",
          start_time=datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc),
          market_type="shots_team", n_outcomes=2, selection="over", line=7.5, team_scope="home",
          odds=2.00, url="https://gol.example", scraped_at=datetime.now(timezone.utc)),
    ]
    opp = scout.evaluate(pool)[0]
    await repo.save(opp)
    rows = await repo.list_recent()
    assert rows[0].n_issues == 2
    assert rows[0].bookmaker_c is None
    assert rows[0].cote_c is None


@pytest.mark.asyncio
async def test_save_if_new_ignore_les_doublons(repo):
    """Le scanner repasse sur les memes matchs : on ne veut pas cinquante lignes."""
    scout = Scout(bankroll=50_000.0)
    pool = [
        _odd("Paryaj Lakay", "home", 3.55),
        _odd("1xBet", "draw", 3.90),
        _odd("Golcash", "away", 3.30),
    ]
    opp = scout.evaluate(pool)[0]

    first = await repo.save_if_new(opp)
    assert first is not None

    # Meme detection, cycle suivant : rien de neuf.
    again = scout.evaluate(pool)[0]
    assert await repo.save_if_new(again) is None
    assert len(await repo.list_recent()) == 1


@pytest.mark.asyncio
async def test_save_if_new_accepte_une_cote_qui_bouge(repo):
    """Une cote differente, c'est une autre occasion : elle doit etre gardee."""
    scout = Scout(bankroll=50_000.0)
    opp = scout.evaluate([
        _odd("Paryaj Lakay", "home", 3.55),
        _odd("1xBet", "draw", 3.90),
        _odd("Golcash", "away", 3.30),
    ])[0]
    await repo.save_if_new(opp)

    bouge = scout.evaluate([
        _odd("Paryaj Lakay", "home", 3.60),
        _odd("1xBet", "draw", 3.90),
        _odd("Golcash", "away", 3.30),
    ])[0]
    assert await repo.save_if_new(bouge) is not None
    assert len(await repo.list_recent()) == 2
