"""Dashboard web leger FastAPI + HTMX (spec MISSION §8).

Opportunites live, historique, courbe de bankroll, taux de succes des
appariements IA. Endpoints server-rendered (Jinja2) ; les fragments HTMX
rafraichissent la liste sans recharger la page.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..storage.db import make_engine, make_session_factory
from ..storage.repository import OpportunityRepository

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Surebet Haiti — Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_engine = make_engine(settings.database_url)
_repo = OpportunityRepository(make_session_factory(_engine))


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
    rows = await _repo.all()
    recent = sorted(rows, key=lambda r: r.date_detection, reverse=True)[:50]
    context = {
        "opportunities": recent,
        "total": len(rows),
        "bankroll_curve": _bankroll_curve(rows),
        "bankroll_svg": _bankroll_svg(_bankroll_curve(rows)),
        "ai_success_rate": _ai_match_success_rate(rows),
        "total_profit": round(sum(r.profit or 0.0 for r in rows), 2),
    }
    return templates.TemplateResponse(request, "index.html", context)


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
