"""Modeles SQLAlchemy (spec MISSION §8 : table opportunities)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OpportunityRow(Base):
    """Table `opportunities` (colonnes exactes spec MISSION §8).

    Les colonnes bookmaker_C/event_C/cote_C/mise_C restent nulles pour les
    opportunites a 2 issues.
    """

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date_detection: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    match: Mapped[str] = mapped_column(String(255))
    sport: Mapped[str] = mapped_column(String(32))
    match_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    n_issues: Mapped[int] = mapped_column(Integer)

    bookmaker_a: Mapped[str] = mapped_column(String(64))
    event_a: Mapped[str] = mapped_column(String(255))
    cote_a: Mapped[float] = mapped_column(Float)
    mise_a: Mapped[float] = mapped_column(Float)
    url_a: Mapped[str] = mapped_column(Text, default="")

    bookmaker_b: Mapped[str] = mapped_column(String(64))
    event_b: Mapped[str] = mapped_column(String(255))
    cote_b: Mapped[float] = mapped_column(Float)
    mise_b: Mapped[float] = mapped_column(Float)
    url_b: Mapped[str] = mapped_column(Text, default="")

    bookmaker_c: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_c: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cote_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    mise_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    url_c: Mapped[str | None] = mapped_column(Text, nullable=True)

    marge_m: Mapped[float] = mapped_column(Float)
    roi_pct: Mapped[float] = mapped_column(Float)
    profit: Mapped[float] = mapped_column(Float)
    init_balance: Mapped[float] = mapped_column(Float)
    final_balance: Mapped[float] = mapped_column(Float)
    score_ia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    statut: Mapped[str] = mapped_column(String(32), default="detected")


class NormalizationCacheRow(Base):
    """Cache persistant libelle -> mapping (spec MISSION §6.1)."""

    __tablename__ = "normalization_cache"

    cache_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    market_type: Mapped[str] = mapped_column(String(64))
    selection: Mapped[str] = mapped_column(String(16))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    team_scope: Mapped[str | None] = mapped_column(String(8), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
