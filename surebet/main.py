"""Orchestrateur asyncio (spec MISSION §3, §8, §9).

Cycle : scrape (30s pre-match / 10s live) -> normalize -> detect -> score ->
store -> notify. Journalisation par bookmaker ; alerte si indisponibilite > 5 min.
Le mode --dry-run rejoue les fixtures locales (aucun reseau) pour reproduire un
cycle complet sur les exemples de reference §5.4/§5.5.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .ai.scorer import ScoringContext, score_opportunity
from .ai.scout import Scout
from .config import settings
from .normalizer.ai_normalizer import AiNormalizer, AnthropicLLMClient, HourlyBudget
from .normalizer.schema import Odd
from .notifier.telegram import TelegramNotifier, should_alert
from .scrapers.base import ScraperUnavailableError
from .scrapers.golcash import GolcashScraper
from .scrapers.parsing import MatchMeta, extract_markets_from_html, raw_markets_to_odds
from .scrapers.paryajlakay import ParyajLakayScraper
from .scrapers.paryajpam import ParyajPamScraper
from .scrapers.xbet import XBetScraper
from .storage.db import init_db, make_engine, make_session_factory
from .storage.repository import OpportunityRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("surebet.main")

FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def build_scrapers():
    return [
        XBetScraper(base_url=settings.xbet_base_url),
        ParyajLakayScraper(base_url=settings.paryajlakay_base_url),
        ParyajPamScraper(base_url=settings.paryajpam_base_url),
        GolcashScraper(base_url=settings.golcash_base_url),
    ]


def build_llm_client():
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicLLMClient(settings.anthropic_api_key, settings.anthropic_model)
    logger.info("Aucun client LLM configure : normalisation et explications en mode deterministe")
    return None


async def scrape_all(scrapers, sport: str) -> list[Odd]:
    """Scrape tous les bookmakers ; journalise chaque echec (spec MISSION §9)."""
    pool: list[Odd] = []
    for scraper in scrapers:
        try:
            async with scraper:
                odds = await scraper.scrape(sport)
            logger.info("%s: %d cotes recuperees (%s)", scraper.bookmaker_name, len(odds), sport)
            pool.extend(odds)
        except ScraperUnavailableError as exc:
            logger.error("%s indisponible: %s", scraper.bookmaker_name, exc)
            _check_unavailability(scraper)
        except Exception:
            logger.exception("%s: erreur inattendue de scraping", scraper.bookmaker_name)
    return pool


def _check_unavailability(scraper) -> None:
    elapsed = scraper.seconds_since_last_success
    if elapsed is not None and elapsed > settings.scraper_unavailable_alert_after_s:
        logger.critical(
            "ALERTE: %s indisponible depuis %.0f s (> %d s)",
            scraper.bookmaker_name, elapsed, settings.scraper_unavailable_alert_after_s,
        )


async def process_cycle(pool: list[Odd], scout: Scout, notifier: TelegramNotifier,
                        repo: OpportunityRepository | None, prematch: bool = True):
    """normalize (deja fait au scraping) -> detect -> score -> store -> notify.

    `prematch=True` (defaut en temps reel) : n'arbitre que les matchs pas encore
    commences. Le --dry-run le desactive (fixtures aux dates de reference figees).
    """
    fresh_pool = [o for o in pool if not o.is_stale]  # filtre > 60s (spec MISSION §9)
    if prematch:
        now = datetime.now(timezone.utc)
        fresh_pool = [o for o in fresh_pool if o.start_time.astimezone(timezone.utc) > now]
    opportunities = scout.evaluate(fresh_pool)
    logger.info("%d opportunite(s) detectee(s)", len(opportunities))

    doublons = 0
    silencieuses = 0
    for opp in opportunities:
        # Cotes STRICTEMENT identiques : rien de neuf, on n'enregistre meme
        # pas. C'est ce qui produisait 893 lignes en base pour 17 opportunites.
        if repo is not None and await repo.exists(opp):
            doublons += 1
            continue

        # Ce MATCH a-t-il deja donne lieu a une alerte ? Une seule par match,
        # meme si une cote bouge, meme sur un autre marche. Une cote qui
        # derive d'un centieme est techniquement une autre occasion, mais
        # l'abonne y voit le meme surebet repete — et trois alertes pour un
        # match usent la confiance plus qu'elles n'informent.
        deja_signale = repo is not None and await repo.match_deja_signale(opp)

        opp.score_ia = score_opportunity(opp, ScoringContext())
        # L'explication IA ne sert qu'a l'alerte : inutile de la payer pour
        # une evolution qu'on n'enverra pas.
        if not deja_signale:
            opp.explanation = await scout.explain(opp)

        # On enregistre quand meme : l'historique des cotes sert au carnet
        # de bord, et il ne coute rien. Seul l'envoi est limite.
        if repo is not None:
            await repo.save(opp)

        if deja_signale:
            silencieuses += 1
            continue

        if should_alert(opp, settings.min_roi_alert_pct, settings.min_score_alert,
                        settings.alert_only_bookmaker):
            sent = await notifier.send(opp)
            logger.info("Alerte %s (ROI %.2f%%, score %d) : envoi=%s",
                        opp.match_label, opp.roi_pct, opp.score_ia, sent)
    if doublons:
        logger.info("%d doublon(s) ignore(s) (cotes identiques)", doublons)
    if silencieuses:
        logger.info("%d evolution(s) enregistree(s) sans alerte (match deja signale)",
                    silencieuses)
    return opportunities


async def run_loop(sport: str = "football") -> None:
    engine = make_engine(settings.database_url)
    await init_db(engine)
    repo = OpportunityRepository(make_session_factory(engine))
    scrapers = build_scrapers()
    scout = Scout(min_roi=1.0, bankroll=settings.default_bankroll, llm_client=build_llm_client())
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)

    logger.info("Demarrage de la boucle surebet (sport=%s)", sport)
    try:
        while True:
            pool = await scrape_all(scrapers, sport)
            await process_cycle(pool, scout, notifier, repo)
            await asyncio.sleep(settings.scrape_interval_prematch_s)
    finally:
        await engine.dispose()


async def run_collector_loop(sport: str = "football") -> None:
    """Mode collector : collecte continue decouplee de l'evaluation.

    Chaque bookmaker alimente le pool a sa propre cadence via une session
    navigateur persistante ; une boucle d'evaluation independante lit des
    instantanes frais et declenche la detection. C'est le mode recommande en
    production (voir collector/session.py pour le contournement Cloudflare).
    """
    from .collector.pool import OddsPool
    from .collector.service import Collector, CollectorTask
    from .collector.session import BrowserSession

    engine = make_engine(settings.database_url)
    await init_db(engine)
    repo = OpportunityRepository(make_session_factory(engine))
    scout = Scout(min_roi=1.0, bankroll=settings.default_bankroll, llm_client=build_llm_client())
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)

    pool = OddsPool(max_age_s=settings.odds_max_age_s)
    scrapers = build_scrapers()
    sessions: list[BrowserSession] = []

    # Une session navigateur persistante par scraper base navigateur.
    for scraper in scrapers:
        if hasattr(scraper, "attach_session"):
            session = BrowserSession(
                name=scraper.bookmaker_name,
                headless=settings.browser_headless,
                profile_dir=Path(settings.browser_profile_dir) / scraper.bookmaker_name.replace(" ", "_"),
            )
            scraper.attach_session(session)
            sessions.append(session)

    async def alert_unavailable(health) -> None:
        logger.critical("Bookmaker %s injoignable — collecte degradee", health.bookmaker)

    tasks = [
        CollectorTask(scraper=s, interval_s=settings.scrape_interval_prematch_s, sport=sport)
        for s in scrapers
    ]
    collector = Collector(
        pool, tasks,
        unavailable_alert_after_s=settings.scraper_unavailable_alert_after_s,
        on_unavailable=alert_unavailable,
        jitter_s=2.0,
    )

    async def evaluation_loop() -> None:
        while True:
            snapshot = await pool.snapshot()
            if snapshot:
                await process_cycle(snapshot, scout, notifier, repo)
            else:
                logger.info("Pool vide, en attente de collecte")
            await asyncio.sleep(settings.evaluation_interval_s)

    logger.info("Demarrage du mode collector (sport=%s, headless=%s)", sport, settings.browser_headless)
    await collector.start()
    try:
        await evaluation_loop()
    except asyncio.CancelledError:
        pass
    finally:
        await collector.stop()
        for session in sessions:
            await session.stop()
        await engine.dispose()


async def run_scan(sport: str = "football", open_dashboard: bool = False) -> int:
    """Scan unique : collecte les 4 books, detecte, enregistre, rapporte.

    Mode concu pour un usage quotidien (lanceur bureau) : une passe, un
    rapport lisible en console, un export Excel, puis sortie. Retourne le
    nombre d'opportunites detectees (code de sortie du processus).
    """
    from .export.excel import export_opportunities

    engine = make_engine(settings.database_url)
    await init_db(engine)
    repo = OpportunityRepository(make_session_factory(engine))
    scout = Scout(min_roi=1.0, bankroll=settings.default_bankroll, llm_client=build_llm_client())
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)

    print("=" * 66)
    print(f"  SCAN SUREBET — {datetime.now().strftime('%d/%m/%Y %H:%M')} — {sport}")
    print("=" * 66)

    try:
        pool: list[Odd] = []
        for scraper in build_scrapers():
            name = scraper.bookmaker_name
            try:
                odds = await scraper.scrape(sport)
                pool.extend(odds)
                print(f"  [OK]     {name:<14} {len(odds):>6} cotes")
            except ScraperUnavailableError as exc:
                print(f"  [ECHEC]  {name:<14} indisponible — {str(exc)[:40]}")
            except Exception as exc:
                print(f"  [ERREUR] {name:<14} {type(exc).__name__}: {str(exc)[:40]}")

        print(f"\n  Total collecte : {len(pool)} cotes")
        opportunities = await process_cycle(pool, scout, notifier, repo)

        print("-" * 66)
        if not opportunities:
            print("  Aucune opportunite d'arbitrage pour le moment.")
            print("  (Normal : les fenetres durent quelques minutes ; relancer plus tard")
            print("   ou utiliser --collector pour une surveillance continue.)")
        else:
            print(f"  {len(opportunities)} OPPORTUNITE(S) DETECTEE(S)\n")
            for opp in opportunities:
                print(f"  >> {opp.match_label}  [{opp.market_type}"
                      + (f" {opp.line}" if opp.line is not None else "") + "]")
                print(f"     ROI {opp.roi_pct:.2f}%  profit {opp.profit:,.0f} HTG"
                      f"  score IA {opp.score_ia}")
                for leg in opp.legs:
                    print(f"       - {leg.selection:<6} @ {leg.odds:<6} chez {leg.bookmaker:<12}"
                          f" miser {leg.stake:,.0f} HTG")
                print()
            try:
                path = export_opportunities(opportunities, "surebet_opportunites.xlsx")
                print(f"  Export Excel : {path}")
            except Exception as exc:
                logger.warning("Export Excel impossible : %s", exc)
        print("=" * 66)

        if open_dashboard:
            _launch_dashboard()
        return len(opportunities)
    finally:
        await engine.dispose()


def _launch_dashboard() -> None:
    """Ouvre le dashboard dans le navigateur par defaut."""
    import subprocess
    import sys
    import threading
    import webbrowser

    url = f"http://127.0.0.1:{settings.dashboard_port}"
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "surebet.dashboard.app:app",
         "--host", "127.0.0.1", "--port", str(settings.dashboard_port), "--log-level", "warning"],
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    threading.Timer(2.5, lambda: webbrowser.open(url)).start()
    print(f"  Dashboard : {url}   (Ctrl+C pour quitter)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


async def run_dry_run() -> None:
    """Rejoue les fixtures locales : cycle complet sans reseau (spec plan §Verification)."""
    logger.info("=== DRY RUN (fixtures locales, aucun reseau) ===")
    pool = _load_fixture_pool()
    scout = Scout(min_roi=1.0, bankroll=settings.default_bankroll)
    notifier = TelegramNotifier(None, None)
    # prematch=False : les fixtures ont des dates de reference figees (passees)
    opportunities = await process_cycle(pool, scout, notifier, repo=None, prematch=False)

    for opp in opportunities:
        print(f"\n[{opp.n_outcomes} issues] {opp.match_label} — {opp.market_type}")
        print(f"  M={opp.margin:.5f}  ROI={opp.roi_pct:.2f}%  profit={opp.profit:.0f} HTG  score={opp.score_ia}")
        for leg in opp.legs:
            print(f"   - {leg.selection} @ {leg.odds} chez {leg.bookmaker} : {leg.stake:.0f} HTG")
    logger.info("=== DRY RUN termine : %d opportunite(s) ===", len(opportunities))


def _load_fixture_pool() -> list[Odd]:
    """Construit un pool cross-bookmakers a partir des fixtures reelles + des
    cotes des exemples §5.4/§5.5, pour qu'un surebet soit detecte hors-ligne.
    """
    pool: list[Odd] = []
    now = datetime.now(timezone.utc)

    # 1xBet depuis le JSON LineFeed reel
    xbet_payload = json.loads((FIXTURES / "xbet_get1x2.json").read_text(encoding="utf-8"))
    scraper = XBetScraper()
    for event in xbet_payload["Value"]:
        pool.extend(scraper._parse_event(event, "football", now))

    # Paryaj Lakay depuis le HTML evenement reel
    html = (FIXTURES / "paryajlakay_event.html").read_text(encoding="utf-8")
    meta = MatchMeta(
        bookmaker="Paryaj Lakay", sport="football", competition="Copa Sudamericana",
        home_team="Club Bolivar", away_team="Gremio Porto Alegrense",
        start_time=datetime(2026, 7, 23, 18, 0, tzinfo=timezone.utc),
        url="https://www.paryajlakay.com/sports/event/club-bolivar-gremio-m76289162",
    )
    pool.extend(raw_markets_to_odds(extract_markets_from_html(html), meta))

    # Exemples de reference §5.4 (2 issues) et §5.5 (3 issues) pour garantir des surebets
    pool.extend(_reference_example_odds(now))
    return pool


def _reference_example_odds(now: datetime) -> list[Odd]:
    def mk(bk, sport, comp, home, away, mtype, n, sel, line, scope, odds, start):
        return Odd(
            bookmaker=bk, sport=sport, competition=comp, match_id="",
            home_team=home, away_team=away, start_time=start, market_type=mtype,
            n_outcomes=n, selection=sel, line=line, team_scope=scope, odds=odds,
            url=f"https://{bk}.example/bet", scraped_at=now,
        )

    from .normalizer.schema import make_match_id

    start = datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc)
    # §5.4 : Colombie vs Ghana, tirs total Ghana 7.5 -> Paryaj Pam under 2.16 / Golcash over 2.00
    mid_2 = make_match_id("Colombie", "Ghana", start)
    two_way = [
        mk("Paryaj Pam", "football", "Amical", "Colombie", "Ghana", "shots_team", 2, "under", 7.5, "away", 2.16, start),
        mk("Golcash", "football", "Amical", "Colombie", "Ghana", "shots_team", 2, "over", 7.5, "away", 2.00, start),
    ]
    # §5.5 : 1X2 sur 3 bookmakers -> 3.55 / 3.90 / 3.30
    mid_3 = make_match_id("Real Test", "FC Exemple", start)
    three_way = [
        mk("Paryaj Lakay", "football", "Amical", "Real Test", "FC Exemple", "1x2", 3, "home", None, None, 3.55, start),
        mk("1xBet", "football", "Amical", "Real Test", "FC Exemple", "1x2", 3, "draw", None, None, 3.90, start),
        mk("Golcash", "football", "Amical", "Real Test", "FC Exemple", "1x2", 3, "away", None, None, 3.30, start),
    ]
    for o in two_way:
        object.__setattr__(o, "match_id", mid_2)
    for o in three_way:
        object.__setattr__(o, "match_id", mid_3)
    return two_way + three_way


def main() -> None:
    parser = argparse.ArgumentParser(description="Systeme de detection de surebets - marche haitien")
    parser.add_argument("--dry-run", action="store_true", help="Rejoue les fixtures locales sans reseau")
    parser.add_argument("--scan", action="store_true",
                        help="Scan unique des 4 bookmakers + rapport (usage quotidien)")
    parser.add_argument("--dashboard", action="store_true",
                        help="Avec --scan : ouvre le dashboard dans le navigateur")
    parser.add_argument("--collector", action="store_true",
                        help="Mode collector : sessions navigateur persistantes, collecte decouplee (recommande en prod)")
    parser.add_argument("--sport", default="football", choices=["football", "basketball"])
    args = parser.parse_args()

    if args.dry_run:
        asyncio.run(run_dry_run())
    elif args.scan:
        asyncio.run(run_scan(args.sport, open_dashboard=args.dashboard))
    elif args.collector:
        asyncio.run(run_collector_loop(args.sport))
    else:
        asyncio.run(run_loop(args.sport))


if __name__ == "__main__":
    main()
