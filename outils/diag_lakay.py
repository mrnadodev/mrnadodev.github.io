# -*- coding: utf-8 -*-
"""Diagnostic ciblé : que voit RÉELLEMENT le navigateur du VPS sur Paryaj Lakay ?

Le 8 août 2026, ce bookmaker renvoyait 0 cote depuis le serveur alors que la
page s'affiche normalement depuis un poste en Haïti. Quatre hypothèses sont
tombées l'une après l'autre :

  · la mémoire      — la machine était saturée, mais l'échec persiste après
                      redémarrage, avec 20 Go de mémoire validée libre ;
  · le mode invisible — l'échec persiste aussi avec BROWSER_HEADLESS=false ;
  · Cloudflare      — il n'y en a pas : le site répond « Server: IIS/10.0 » ;
  · l'adresse IP    — le VPS et le poste haïtien obtiennent des réponses
                      identiques au bit près sur les trois points d'entrée.

Il ne reste que le rendu. Ce script ne suppose rien : il ouvre la page avec
la MÊME session navigateur que le collecteur, puis enregistre ce qu'il voit —
adresse finale, titre, taille du HTML, nombre de liens de match, requêtes en
échec, et une capture d'écran. On regarde, ensuite on corrige.

    python outils\\diag_lakay.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from surebet.collector.session import BrowserSession   # noqa: E402
from surebet.config import settings                    # noqa: E402

URL = "https://www.paryajlakay.com/sports"
SELECTEUR = "a[href*='/sports/event/']"
LOGS = RACINE / "logs"


async def principal() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    print(f"headless = {settings.browser_headless}   profil = {settings.browser_profile_dir}")

    session = BrowserSession(
        name="Diag Lakay",
        headless=settings.browser_headless,
        profile_dir=settings.browser_profile_dir,
    )
    await session.start()
    page = session._page          # accès direct : c'est un outil de diagnostic

    echecs: list[str] = []
    page.on("requestfailed",
            lambda r: echecs.append(f"{r.failure} {r.url[:110]}"))
    page.on("response",
            lambda r: echecs.append(f"HTTP {r.status} {r.url[:110]}")
            if r.status >= 400 else None)

    print(f"\nNavigation vers {URL} …")
    await page.goto(URL, wait_until="domcontentloaded", timeout=45000)

    # On laisse largement le temps au JavaScript de peupler la liste : le
    # collecteur attend le sélecteur, ici on veut voir l'état APRÈS l'attente,
    # même si le sélecteur n'arrive jamais.
    for seconde in (5, 10, 20):
        await page.wait_for_timeout(5000 if seconde == 5 else 5000 if seconde == 10 else 10000)
        n = await page.locator(SELECTEUR).count()
        print(f"  après {seconde:>2} s : {n} lien(s) de match")
        if n:
            break

    html = await page.content()
    titre = await page.title()
    liens = await page.locator(SELECTEUR).count()

    (LOGS / "lakay.html").write_text(html, encoding="utf-8")
    await page.screenshot(path=str(LOGS / "lakay.png"), full_page=False)

    print("\n─── ce que voit le navigateur du serveur ───")
    print(f"  adresse finale : {page.url}")
    print(f"  titre          : {titre!r}")
    print(f"  HTML           : {len(html)} octets")
    print(f"  liens de match : {liens}")

    # Les mots qui trahissent un blocage, une redirection ou une fenêtre
    # bloquante — plus fiable qu'une lecture à l'œil de 400 Ko de HTML.
    bas = html.lower()
    for mot in ("access denied", "forbidden", "blocked", "captcha", "verify",
                "not available in your", "restricted", "maintenance",
                "cookie", "age", "18+", "geo"):
        if mot in bas:
            print(f"  ⚠ le HTML contient « {mot} »")

    if echecs:
        print("\n─── requêtes en échec ou en erreur ───")
        for e in dict.fromkeys(echecs):
            print(f"  {e}")
    else:
        print("\n  aucune requête en échec")

    print(f"\nEnregistré : {LOGS / 'lakay.html'}")
    print(f"           : {LOGS / 'lakay.png'}")
    await session.stop()
    return 0 if liens else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(principal()))
