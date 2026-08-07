"""Persistance des opportunites et du cache de normalisation (CRUD async)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..normalizer.markets import MarketMatch
from ..normalizer.schema import Opportunity
from .models import NormalizationCacheRow, OpportunityRow


def opportunity_to_row(opp: Opportunity) -> OpportunityRow:
    legs = opp.legs
    a = legs[0]
    b = legs[1]
    c = legs[2] if len(legs) > 2 else None
    return OpportunityRow(
        date_detection=opp.detected_at,
        match=opp.match_label,
        sport=opp.sport,
        match_date=opp.match_date,
        n_issues=opp.n_outcomes,
        bookmaker_a=a.bookmaker, event_a=a.event_label, cote_a=a.odds, mise_a=a.stake, url_a=a.url,
        bookmaker_b=b.bookmaker, event_b=b.event_label, cote_b=b.odds, mise_b=b.stake, url_b=b.url,
        bookmaker_c=c.bookmaker if c else None,
        event_c=c.event_label if c else None,
        cote_c=c.odds if c else None,
        mise_c=c.stake if c else None,
        url_c=c.url if c else None,
        marge_m=opp.margin,
        roi_pct=opp.roi_pct,
        profit=opp.profit,
        init_balance=opp.bankroll,
        final_balance=opp.bankroll + opp.profit,
        score_ia=opp.score_ia,
        explanation=opp.explanation,
        statut=opp.status,
    )


class OpportunityRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, opp: Opportunity) -> int:
        async with self._session_factory() as session:
            row = opportunity_to_row(opp)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    async def exists(self, opp: Opportunity) -> bool:
        """La meme opportunite est-elle deja en base ?

        Le scanner repasse sur les memes matchs a chaque cycle. Sans ce
        filtre, une opportunite qui reste ouverte dix minutes produit une
        ligne par scan : la base finit par contenir cinquante fois la meme
        chose, et le signal reel se perd dans les repetitions.

        Deux detections sont identiques si le match, le marche et TOUTES
        les cotes le sont. Une cote qui bouge, meme d'un centieme, est une
        autre occasion avec un autre profit : elle n'est pas un doublon.
        """
        c = opportunity_to_row(opp)
        async with self._session_factory() as session:
            found = await session.execute(
                select(OpportunityRow.id).where(
                    OpportunityRow.match == c.match,
                    OpportunityRow.n_issues == c.n_issues,
                    OpportunityRow.event_a == c.event_a,
                    OpportunityRow.cote_a == c.cote_a,
                    OpportunityRow.bookmaker_a == c.bookmaker_a,
                    OpportunityRow.event_b == c.event_b,
                    OpportunityRow.cote_b == c.cote_b,
                    OpportunityRow.bookmaker_b == c.bookmaker_b,
                    OpportunityRow.event_c == c.event_c,
                    OpportunityRow.cote_c == c.cote_c,
                    OpportunityRow.bookmaker_c == c.bookmaker_c,
                ).limit(1)
            )
            return found.scalar_one_or_none() is not None

    async def match_deja_signale(self, opp: Opportunity) -> bool:
        """Ce MATCH a-t-il deja donne lieu a une alerte ?

        Distinct de exists(), qui compare les cotes. Ici on ignore et les
        cotes et le marche : un seul signal par match, meme si une cote
        bouge, meme si un autre marche du meme match devient interessant.

        Pourquoi cette regle plus large : une cote qui derive d'un centieme
        est techniquement une autre occasion, mais l'abonne recoit le
        sentiment du meme surebet repete. Trois alertes pour un seul match
        usent la confiance plus qu'elles n'apportent d'information.

        On continue en revanche d'ENREGISTRER chaque evolution : l'historique
        des cotes sert au carnet de bord et ne coute rien. Seul l'envoi est
        limite.
        """
        c = opportunity_to_row(opp)
        async with self._session_factory() as session:
            found = await session.execute(
                select(OpportunityRow.id).where(
                    OpportunityRow.match == c.match,
                    OpportunityRow.sport == c.sport,
                ).limit(1)
            )
            return found.scalar_one_or_none() is not None

    async def save_if_new(self, opp: Opportunity) -> int | None:
        """Enregistre l'opportunite, sauf si la meme est deja en base.

        Retourne l'id insere, ou None si c'etait un doublon.
        """
        if await self.exists(opp):
            return None
        return await self.save(opp)

    async def list_recent(self, limit: int = 50) -> list[OpportunityRow]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OpportunityRow).order_by(OpportunityRow.date_detection.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def all(self) -> list[OpportunityRow]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OpportunityRow).order_by(OpportunityRow.date_detection.asc())
            )
            return list(result.scalars().all())


class SqlNormalizationCache:
    """Cache de normalisation persistant (spec MISSION §6.1).

    Implemente l'interface get/set attendue par AiNormalizer, adossee a SQLite.
    Les acces sont synchrones cote appelant (le pipeline de normalisation n'est
    pas dans le chemin critique) : on ouvre une session courte par operation.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._memory: dict[str, MarketMatch] = {}

    def get(self, key: str) -> MarketMatch | None:
        return self._memory.get(key)

    def set(self, key: str, value: MarketMatch) -> None:
        self._memory[key] = value

    async def load(self) -> None:
        """Precharge le cache SQL en memoire au demarrage."""
        async with self._session_factory() as session:
            result = await session.execute(select(NormalizationCacheRow))
            for row in result.scalars().all():
                self._memory[row.cache_key] = MarketMatch(
                    market_type=row.market_type,
                    selection=row.selection,
                    n_outcomes=3 if row.selection in ("home", "draw", "away") else 2,
                    line=row.line,
                    team_scope=row.team_scope,
                    confidence=row.confidence,
                )

    async def persist(self, key: str, value: MarketMatch) -> None:
        self.set(key, value)
        async with self._session_factory() as session:
            existing = await session.get(NormalizationCacheRow, key)
            if existing is None:
                session.add(
                    NormalizationCacheRow(
                        cache_key=key,
                        market_type=value.market_type,
                        selection=value.selection,
                        line=value.line,
                        team_scope=value.team_scope,
                        confidence=value.confidence,
                    )
                )
                await session.commit()
