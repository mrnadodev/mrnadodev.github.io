"""Dashboard web leger FastAPI + HTMX (spec MISSION §8).

Opportunites live, historique, courbe de bankroll, taux de succes des
appariements IA. Endpoints server-rendered (Jinja2) ; les fragments HTMX
rafraichissent la liste sans recharger la page.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..normalizer.schema import Odd
from ..scrapers.base import ScraperUnavailableError
from ..storage.db import make_engine, make_session_factory
from ..storage.repository import OpportunityRepository
from .live import LiveOpportunity, rank_cross_book, scan_stats

logger = logging.getLogger("surebet.dashboard")

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Surebet Haiti — Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_engine = make_engine(settings.database_url)
_repo = OpportunityRepository(make_session_factory(_engine))

# Books a API rapide (sans navigateur) : reponse en quelques secondes, adaptes
# a un scan declenche depuis le web. Paryaj Lakay (Playwright) est optionnel.
FAST_BOOKMAKERS = ("1xBet", "Golcash", "Paryaj Pam")


def _build_fast_scrapers(exclude: set[str]):
    from ..scrapers.golcash import GolcashScraper
    from ..scrapers.paryajpam import ParyajPamScraper
    from ..scrapers.xbet import XBetScraper

    candidates = [
        XBetScraper(base_url=settings.xbet_base_url),
        GolcashScraper(base_url=settings.golcash_base_url),
        ParyajPamScraper(base_url=settings.paryajpam_base_url),
    ]
    return [s for s in candidates if s.bookmaker_name not in exclude]


async def _live_scan(sport: str, min_roi: float, exclude: set[str]) -> dict:
    """Scan en direct des books rapides -> stats + opportunites classees."""
    pool: list[Odd] = []
    up: list[str] = []
    down: list[str] = []
    for scraper in _build_fast_scrapers(exclude):
        try:
            odds = await scraper.scrape(sport)
            pool.extend(odds)
            up.append(scraper.bookmaker_name)
        except (ScraperUnavailableError, Exception) as exc:  # noqa: BLE001
            logger.warning("Scan live: %s indisponible (%s)", scraper.bookmaker_name, exc)
            down.append(scraper.bookmaker_name)

    ranked = rank_cross_book(pool, bankroll=settings.default_bankroll)
    filtered = [o for o in ranked if o.roi_pct >= min_roi] if min_roi > 0 else ranked
    stats = scan_stats(pool, ranked)
    stats["bookmakers_down"] = down
    return {
        "stats": stats,
        "opportunities": [o.to_dict() for o in filtered],
        "sport": sport,
        "min_roi": min_roi,
    }


def _bankroll_curve(rows) -> list[dict]:
    """Cumule les profits dans l'ordre chronologique -> courbe de bankroll."""
    curve = []
    cumulative = 0.0
    for row in sorted(rows, key=lambda r: r.date_detection):
        cumulative += row.profit or 0.0
        curve.append({"t": row.date_detection.isoformat(), "cumulative_profit": round(cumulative, 2)})
    return curve


def _bankroll_svg(curve: list[dict], width: int = 900, height: int = 160) -> str:
    """Sparkline SVG du profit cumule (aucune dependance JS externe)."""
    if not curve:
        return '<svg viewBox="0 0 900 160"><text x="20" y="85" fill="#8aa">Pas encore de données</text></svg>'
    values = [p["cumulative_profit"] for p in curve]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    pad = 10
    pts = []
    for i, v in enumerate(values):
        x = pad + (width - 2 * pad) * (i / max(n - 1, 1))
        y = height - pad - (height - 2 * pad) * ((v - lo) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="#137333" stroke-width="2" points="{polyline}"/>'
        f'</svg>'
    )


def _ai_match_success_rate(rows) -> float:
    """Taux d'opportunites dont le score IA a franchi le seuil d'alerte."""
    scored = [r for r in rows if r.score_ia is not None]
    if not scored:
        return 0.0
    passed = sum(1 for r in scored if r.score_ia >= settings.min_score_alert)
    return round(100.0 * passed / len(scored), 1)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "default_min_profit": settings.min_roi_alert_pct,
        "bookmakers": list(FAST_BOOKMAKERS),
    })


@app.get("/api/scan")
async def api_scan(sport: str = "football", min_profit: float = 0.0, exclude: str = ""):
    """Scan en direct : cotes par issue, surebets et quasi-surebets."""
    excluded = {b.strip() for b in exclude.split(",") if b.strip()}
    return await _live_scan(sport, min_profit, excluded)


@app.get("/fragments/opportunities", response_class=HTMLResponse)
async def opportunities_fragment(request: Request):
    rows = await _repo.list_recent(limit=50)
    return templates.TemplateResponse(
        request, "_opportunities.html", {"opportunities": rows}
    )


@app.get("/api/opportunities")
async def api_opportunities():
    rows = await _repo.list_recent(limit=100)
    return [
        {
            "match": r.match, "sport": r.sport, "n_issues": r.n_issues,
            "roi_pct": r.roi_pct, "profit": r.profit, "score_ia": r.score_ia,
            "marge_m": r.marge_m, "statut": r.statut,
            "date_detection": r.date_detection.isoformat(),
        }
        for r in rows
    ]
