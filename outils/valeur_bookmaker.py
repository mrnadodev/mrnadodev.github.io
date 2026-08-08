# -*- coding: utf-8 -*-
"""Combien vaut chaque bookmaker dans vos occasions passées ?

Écrit le 8 août 2026, quand l'API de Paryaj Lakay s'est mise à refuser
l'adresse du VPS. Trois montages permettraient de contourner ce refus — un
relais résidentiel haïtien, un tunnel permanent par le bureau, un second
collecteur sur une machine en Haïti — et tous coûtent de l'argent ou de la
fiabilité.

Décider sans chiffre, c'est parier. Ce script répond à la seule question qui
compte avant d'engager quoi que ce soit : sur les occasions réellement
détectées, dans combien Paryaj Lakay est-il une jambe indispensable ?

  · « présent »        : le bookmaker figure dans l'occasion ;
  · « indispensable »  : sans lui, l'occasion n'existe pas — c'est le vrai
                         coût de sa perte, car une occasion à trois jambes
                         dont deux viennent d'ailleurs peut survivre.

    python outils\\valeur_bookmaker.py [--jours 30]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BASE = RACINE / "surebet.db"


def principal() -> int:
    ap = argparse.ArgumentParser(description="Poids de chaque bookmaker dans les occasions détectées")
    ap.add_argument("--jours", type=int, default=30, help="fenêtre d'analyse (défaut : 30)")
    args = ap.parse_args()

    if not BASE.exists() or BASE.stat().st_size == 0:
        print(f"Base introuvable ou vide : {BASE}", file=sys.stderr)
        return 1

    depuis = (datetime.now(timezone.utc) - timedelta(days=args.jours)).isoformat()
    con = sqlite3.connect(f"file:{BASE}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    lignes = con.execute(
        "select bookmaker_a, bookmaker_b, bookmaker_c, roi_pct, sport, n_issues "
        "from opportunities where date_detection >= ?", (depuis,)
    ).fetchall()
    con.close()

    if not lignes:
        print(f"Aucune occasion enregistrée sur {args.jours} jours.")
        return 1

    total = len(lignes)
    present = Counter()
    indispensable = Counter()
    roi_avec = {}

    for l in lignes:
        books = [b for b in (l["bookmaker_a"], l["bookmaker_b"], l["bookmaker_c"]) if b]
        uniques = set(books)
        for b in uniques:
            present[b] += 1
            roi_avec.setdefault(b, []).append(l["roi_pct"] or 0.0)
            # Un arbitrage exige au moins deux bookmakers distincts. Retirer
            # celui-ci n'en laisse qu'un : l'occasion disparaît avec lui.
            if len(uniques - {b}) < 2:
                indispensable[b] += 1

    print(f"\n  {total} occasions sur {args.jours} jours\n")
    print(f"  {'bookmaker':<16}{'présent':>10}{'indispensable':>16}{'ROI médian':>13}")
    print("  " + "─" * 55)
    for b, n in present.most_common():
        rois = sorted(roi_avec[b])
        median = rois[len(rois) // 2]
        pc_p = 100 * n / total
        pc_i = 100 * indispensable[b] / total
        print(f"  {b:<16}{n:>5} ({pc_p:>4.1f}%){indispensable[b]:>8} ({pc_i:>4.1f}%){median:>12.2f}%")

    perdu = indispensable.get("Paryaj Lakay", 0)
    print()
    if perdu:
        print(f"  Perdre Paryaj Lakay coûte {perdu} occasions sur {total}, soit "
              f"{100*perdu/total:.1f} % — celles où il est indispensable.")
        print(f"  Rapporté à votre rythme : environ {perdu/args.jours:.1f} par jour.")
    else:
        print("  Paryaj Lakay n'est indispensable dans aucune occasion de la période.")
    print("\n  « Indispensable » = sans lui il ne resterait qu'un seul bookmaker,")
    print("  donc plus d'arbitrage possible. C'est le coût réel de sa perte,")
    print("  et non le simple nombre d'occasions où il apparaît.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
