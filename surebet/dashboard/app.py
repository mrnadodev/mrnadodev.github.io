"""Dashboard web leger FastAPI + HTMX (spec MISSION §8).

Opportunites live, historique, courbe de bankroll, taux de succes des
appariements IA. Endpoints server-rendered (Jinja2) ; les fragments HTMX
rafraichissent la liste sans recharger la page.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from contextlib import asynccontextmanager

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


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    # Fermeture propre de la session navigateur Paryaj Lakay si elle a servi.
    if _lakay_session is not None:
        await _lakay_session.stop()


app = FastAPI(title="Surebet Haiti — Dashboard", lifespan=_lifespan)
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


# --- Paryaj Lakay : navigateur persistant, reutilise entre les scans ---------
# Optionnel (lent, ~1 min via Playwright). Une seule session est maintenue en
# vie pour eviter de relancer Chromium a chaque scan et pour conserver la
# clearance Cloudflare ; un verrou serialise les scans concurrents.
_lakay_scraper = None
_lakay_session = None
_lakay_lock = asyncio.Lock()
LAKAY_EVENT_LIMIT = 20


async def _scrape_lakay(sport: str) -> list[Odd]:
    global _lakay_scraper, _lakay_session
    from ..collector.session import BrowserSession
    from ..scrapers.paryajlakay import ParyajLakayScraper

    async with _lakay_lock:
        if _lakay_scraper is None:
            _lakay_scraper = ParyajLakayScraper(base_url=settings.paryajlakay_base_url)
            _lakay_session = BrowserSession(name="Paryaj Lakay", headless=settings.browser_headless)
            _lakay_scraper.attach_session(_lakay_session)
            await _lakay_session.start()

        urls = await _lakay_scraper._list_event_urls(sport, limit=LAKAY_EVENT_LIMIT)
        odds: list[Odd] = []
        for url in urls:
            try:
                odds.extend(await _lakay_scraper._scrape_event(url, sport))
            except Exception:
                logger.debug("Scan live: evenement Paryaj Lakay illisible (%s)", url)
        return odds


async def _live_scan(sport: str, min_roi: float, exclude: set[str],
                     include_lakay: bool = False) -> dict:
    """Scan en direct -> stats + opportunites classees.

    Les books rapides tournent en concurrence ; Paryaj Lakay (optionnel, lent)
    est lance en parallele et fusionne au pool s'il repond.
    """
    up: list[str] = []
    down: list[str] = []

    async def run(scraper):
        try:
            odds = await scraper.scrape(sport)
            up.append(scraper.bookmaker_name)
            return odds
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scan live: %s indisponible (%s)", scraper.bookmaker_name, exc)
            down.append(scraper.bookmaker_name)
            return []

    tasks = [run(s) for s in _build_fast_scrapers(exclude)]
    if include_lakay and "Paryaj Lakay" not in exclude:
        async def run_lakay():
            try:
                odds = await _scrape_lakay(sport)
                up.append("Paryaj Lakay")
                return odds
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scan live: Paryaj Lakay indisponible (%s)", exc)
                down.append("Paryaj Lakay")
                return []
        tasks.append(run_lakay())

    pool: list[Odd] = [o for batch in await asyncio.gather(*tasks) for o in batch]

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
        "bookmakers": list(FAST_BOOKMAKERS) + ["Paryaj Lakay"],
    })


@app.get("/api/scan")
async def api_scan(sport: str = "football", min_profit: float = 0.0,
                   exclude: str = "", include_lakay: bool = False):
    """Scan en direct : cotes par issue, surebets et quasi-surebets."""
    excluded = {b.strip() for b in exclude.split(",") if b.strip()}
    return await _live_scan(sport, min_profit, excluded, include_lakay=include_lakay)


@app.get("/api/funbets")
async def api_funbets():
    """FunBets Paryaj Lakay (paris boostes) chiffres contre les cotes 1xBet."""
    from ..funbet.pricing import value_funbet
    from ..scrapers.xbet import XBetScraper

    try:
        funbets = await _scrape_lakay_funbets()
    except Exception as exc:  # noqa: BLE001
        logger.warning("FunBets: extraction impossible (%s)", exc)
        return {"funbets": [], "error": "Paryaj Lakay FunBet indisponible"}

    try:
        async with XBetScraper(base_url=settings.xbet_base_url) as xbet:
            pool = await xbet.scrape("football")
    except Exception as exc:  # noqa: BLE001
        logger.warning("FunBets: 1xBet indisponible pour le pricing (%s)", exc)
        pool = []

    out = []
    for fb in funbets:
        val = value_funbet(fb, pool)
        out.append({
            "match": fb.match,
            "description": fb.description,
            "boosted_odds": fb.boosted_odds,
            "event_url": (settings.paryajlakay_base_url + fb.event_url) if fb.event_url else None,
            "complete": val.complete,
            "fair_odds": round(val.fair_odds, 2) if val.fair_odds else None,
            "edge_pct": round(val.edge_pct, 1) if val.edge_pct is not None else None,
            "unpriced_count": val.unpriced_count,
            "legs": [
                {"label": p.detail or p.condition.raw,
                 "raw": p.condition.raw,
                 "fair_odds": round(p.fair_odds, 2) if p.fair_odds else None,
                 "bookmaker": p.bookmaker}
                for p in val.priced
            ],
        })
    out.sort(key=lambda f: (f["edge_pct"] is None, -(f["edge_pct"] or 0)))
    return {"funbets": out}


async def _scrape_lakay_funbets():
    global _lakay_scraper, _lakay_session
    from ..collector.session import BrowserSession
    from ..scrapers.paryajlakay import ParyajLakayScraper

    async with _lakay_lock:
        if _lakay_scraper is None:
            _lakay_scraper = ParyajLakayScraper(base_url=settings.paryajlakay_base_url)
            _lakay_session = BrowserSession(name="Paryaj Lakay", headless=settings.browser_headless)
            _lakay_scraper.attach_session(_lakay_session)
            await _lakay_session.start()
        return await _lakay_scraper.scrape_funbets()


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
