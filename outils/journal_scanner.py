#!/usr/bin/env python3
"""Carnet de bord du scanner : mesurer sa fiabilite avant de le brancher.

POURQUOI
    Une semaine a regarder passer des alertes Telegram donne une
    impression, pas une mesure. Au bout des sept jours il faut pouvoir
    repondre par un chiffre a : « sur cent detections, combien etaient
    reellement jouables, et quand ca ratait, pourquoi ? »

    Sans ce carnet, la decision de brancher le scanner se prendra au
    ressenti — et le ressenti retient les echecs spectaculaires, pas les
    reussites ordinaires.

LA DISTINCTION QUI COMPTE
    « La cote etait deja partie » n'est PAS une erreur du scanner. C'est
    un probleme de vitesse : la detection etait juste, vous etes arrive
    trop tard. Le remede est la publication automatique, pas une
    correction du detecteur.

    « La cote n'existait pas » ou « ce n'etait pas le meme marche », en
    revanche, sont de vraies erreurs. Les confondre menerait a la
    mauvaise conclusion.

UTILISATION
    python outils/journal_scanner.py             # pointer les detections
    python outils/journal_scanner.py --rapport   # bilan
    python outils/journal_scanner.py --rapport --jours 7
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "surebet.db"

VERDICTS = {
    "1": ("ok", "Jouable : cotes conformes chez les deux bookmakers"),
    "2": ("partie", "Cote deja partie (detection juste, arrivee trop tard)"),
    "3": ("fausse", "Cote introuvable ou differente chez le bookmaker"),
    "4": ("marche", "Les jambes ne sont pas le meme marche"),
    "5": ("match", "Ce n'est pas le meme match"),
    "6": ("doute", "Pas pu verifier"),
}
VRAIES_ERREURS = {"fausse", "marche", "match"}


def _conn() -> sqlite3.Connection:
    if not BASE.exists():
        print(f"Base introuvable : {BASE}", file=sys.stderr)
        raise SystemExit(2)
    c = sqlite3.connect(BASE)
    c.row_factory = sqlite3.Row
    return c


def _distinctes(c: sqlite3.Connection, seulement_non_pointees: bool,
                sport: str | None = None) -> list[sqlite3.Row]:
    """Une ligne par opportunite reelle : la base contient des repetitions
    pour les detections anterieures a la deduplication.

    `sport` filtre le resultat. C'est indispensable des que deux sports
    tournent en parallele : sans lui, le bilan football compterait les
    detections de basket et ne mesurerait plus rien de precis.
    """
    conditions, params = [], []
    if seulement_non_pointees:
        conditions.append("statut = 'detected'")
    if sport:
        conditions.append("sport = ?")
        params.append(sport)
    filtre = ("where " + " and ".join(conditions)) if conditions else ""
    return list(c.execute(f"""
        select min(id) as id, min(date_detection) as vu, match, sport,
               bookmaker_a, event_a, cote_a,
               bookmaker_b, event_b, cote_b,
               bookmaker_c, event_c, cote_c,
               roi_pct, score_ia, statut
        from opportunities
        {filtre}
        group by match, event_a, cote_a, event_b, cote_b, cote_c
        order by min(date_detection)
    """, params))


def pointer(sport: str | None = None) -> int:
    c = _conn()
    lignes = _distinctes(c, True, sport)
    if not lignes:
        print("Rien a pointer : toutes les detections ont deja un verdict.")
        return 0

    print(f"{len(lignes)} detection(s) a pointer. Entree vide = passer, q = quitter.\n")
    for i, r in enumerate(lignes, 1):
        print(f"--- {i}/{len(lignes)} | {r['vu'][:16]} | {r['match']} ({r['sport']})")
        print(f"    ROI {r['roi_pct']:.2f}%  score IA {r['score_ia']}")
        print(f"    A  {r['bookmaker_a']:14} {str(r['event_a'])[:34]:34} @ {r['cote_a']}")
        print(f"    B  {r['bookmaker_b']:14} {str(r['event_b'])[:34]:34} @ {r['cote_b']}")
        if r["cote_c"]:
            print(f"    C  {r['bookmaker_c']:14} {str(r['event_c'])[:34]:34} @ {r['cote_c']}")
        for k, (_, libelle) in VERDICTS.items():
            print(f"      {k} = {libelle}")
        try:
            choix = input("    verdict > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nInterrompu.")
            break
        if choix == "q":
            break
        if choix not in VERDICTS:
            print("    (passe)\n")
            continue
        code = VERDICTS[choix][0]
        # On marque toutes les lignes de cette opportunite, pas seulement la premiere.
        c.execute("""
            update opportunities set statut = ?
            where match = ? and event_a = ? and cote_a = ?
              and event_b = ? and cote_b = ? and ifnull(cote_c,-1) = ifnull(?,-1)
        """, (code, r["match"], r["event_a"], r["cote_a"],
              r["event_b"], r["cote_b"], r["cote_c"]))
        c.commit()
        print(f"    -> {code}\n")
    return 0


def rapport(jours: int, sport: str | None = None) -> int:
    c = _conn()
    # date_detection est ecrit avec datetime.now(timezone.utc) puis stocke
    # SANS fuseau : c'est de l'UTC. Comparer avec datetime.now(), qui rend
    # l'heure LOCALE, decalait donc la fenetre du decalage horaire de la
    # machine — 4 heures depuis Haiti, davantage depuis un VPS mal regle.
    maintenant_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    depuis = (maintenant_utc - timedelta(days=jours)).isoformat(sep=" ")
    lignes = [r for r in _distinctes(c, False, sport) if (r["vu"] or "") >= depuis]

    if not lignes:
        print(f"Aucune detection sur les {jours} derniers jours.")
        print("Le scanner tourne-t-il ? (python outils/controle_sante.py)")
        return 1

    compte = Counter(r["statut"] for r in lignes)
    pointees = [r for r in lignes if r["statut"] != "detected"]
    n = len(lignes)

    entete = f"CARNET DU SCANNER - {jours} derniers jours"
    entete += f" - {sport.upper()}" if sport else " - TOUS SPORTS"
    print(entete)
    print()
    print(f"  Detections distinctes : {n}")
    print(f"  Pointees              : {len(pointees)}")
    if len(pointees) < n:
        print(f"  ATTENTION : {n - len(pointees)} non pointee(s), le bilan est partiel.\n")
    else:
        print()

    if not pointees:
        print("Rien a conclure tant que rien n'est pointe.")
        return 1

    ok = compte.get("ok", 0)
    partie = compte.get("partie", 0)
    erreurs = sum(compte.get(k, 0) for k in VRAIES_ERREURS)
    base = ok + partie + erreurs

    print("  Repartition :")
    for code, libelle in [(v[0], v[1]) for v in VERDICTS.values()]:
        if compte.get(code):
            print(f"    {compte[code]:4}  {libelle}")
    print()

    if base:
        taux_juste = 100.0 * (ok + partie) / base
        taux_vitesse = 100.0 * partie / base
        print(f"  Detections JUSTES     : {taux_juste:.0f} %  (jouables + arrivees trop tard)")
        print(f"  dont perdues de vitesse: {taux_vitesse:.0f} %")
        print(f"  VRAIES erreurs        : {100.0 * erreurs / base:.0f} %")
        print(f"  ROI moyen des jouables : "
              f"{(sum(r['roi_pct'] for r in lignes if r['statut']=='ok') / ok):.2f} %" if ok else "")
        print()
        print("  Lecture :")
        if taux_juste >= 90:
            print("    Le detecteur est fiable. S'il reste des pertes, elles sont")
            print("    de VITESSE : c'est la publication automatique qui les reglera,")
            print("    pas une correction du calcul.")
        elif taux_juste >= 70:
            print("    Utilisable avec une file de validation humaine, mais pas en")
            print("    publication directe. Regardez d'abord les causes ci-dessus.")
        else:
            print("    Ne branchez pas encore. Le probleme est dans la collecte ou")
            print("    la normalisation, pas dans le calcul d'arbitrage.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Carnet de bord du scanner")
    p.add_argument("--rapport", action="store_true", help="afficher le bilan")
    p.add_argument("--jours", type=int, default=7, help="fenetre du bilan (defaut 7)")
    p.add_argument("--sport", choices=["football", "basketball"],
                   help="ne garder qu un sport (indispensable si les deux tournent)")
    a = p.parse_args()
    return rapport(a.jours, a.sport) if a.rapport else pointer(a.sport)


if __name__ == "__main__":
    raise SystemExit(main())
