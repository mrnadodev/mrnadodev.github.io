#!/usr/bin/env python3
"""Sauvegarde coherente de la base du scanner.

POURQUOI PAS UNE SIMPLE COPIE
    Le scanner ecrit en continu. Copier le fichier pendant qu'il travaille
    peut capturer une base au milieu d'une transaction : le fichier existe,
    il pese le bon poids, et il est inexploitable. On ne s'en apercoit que
    le jour ou on essaie de le restaurer — c'est-a-dire le pire jour.

    VACUUM INTO demande a SQLite lui-meme d'ecrire un instantane coherent,
    meme si des ecritures sont en cours. Le resultat est en prime compacte.

    La copie est ensuite RELUE et verifiee : une sauvegarde qu'on n'a pas
    ouverte n'est pas une sauvegarde, c'est une esperance.

UTILISATION
    python outils/sauvegarder_scanner.py
    python outils/sauvegarder_scanner.py --jours 30

Code de sortie 1 en cas d'echec, pour qu'un planificateur puisse alerter.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BASE = RACINE / "surebet.db"
DOSSIER = RACINE / "sauvegardes"


def sauvegarder(garder_jours: int) -> int:
    if not BASE.exists():
        print(f"Base introuvable : {BASE}", file=sys.stderr)
        print("Le scanner n'a peut-etre jamais tourne sur cette machine.", file=sys.stderr)
        return 1

    taille = BASE.stat().st_size
    if taille == 0:
        print(f"ATTENTION : {BASE} est vide (0 octet).", file=sys.stderr)
        print("Rien a sauvegarder : verifiez que le scanner tourne.", file=sys.stderr)
        return 1

    DOSSIER.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    cible = DOSSIER / f"surebet-{horodatage}.db"

    # Instantane coherent, meme si le scanner ecrit en ce moment meme.
    try:
        src = sqlite3.connect(f"file:{BASE}?mode=ro", uri=True)
        try:
            src.execute("VACUUM INTO ?", (str(cible),))
        finally:
            src.close()
    except sqlite3.Error as e:
        print(f"Echec de la sauvegarde : {e}", file=sys.stderr)
        return 1

    # Une sauvegarde qu'on n'a pas relue n'est pas une sauvegarde.
    try:
        v = sqlite3.connect(cible)
        etat = v.execute("pragma integrity_check").fetchone()[0]
        lignes = v.execute("select count(*) from opportunities").fetchone()[0]
        v.close()
    except sqlite3.Error as e:
        print(f"Sauvegarde ILLISIBLE, supprimee : {e}", file=sys.stderr)
        cible.unlink(missing_ok=True)
        return 1

    if etat != "ok":
        print(f"Sauvegarde CORROMPUE ({etat}), supprimee", file=sys.stderr)
        cible.unlink(missing_ok=True)
        return 1

    print(f"Sauvegarde : {cible.name}")
    print(f"  {lignes} detection(s), {cible.stat().st_size:,} octets, integrite verifiee")

    # Rotation
    limite = datetime.now() - timedelta(days=garder_jours)
    retirees = 0
    for f in DOSSIER.glob("surebet-*.db"):
        if datetime.fromtimestamp(f.stat().st_mtime) < limite:
            f.unlink()
            retirees += 1
    if retirees:
        print(f"  {retirees} sauvegarde(s) de plus de {garder_jours} jours effacee(s)")

    restantes = sorted(DOSSIER.glob("surebet-*.db"))
    print(f"  {len(restantes)} sauvegarde(s) conservee(s) dans {DOSSIER}")
    print()
    print("RAPPEL : ces copies vivent sur la MEME machine que la base.")
    print("Si le serveur disparait, elles disparaissent avec. Rapatriez-les")
    print("chez vous une fois par semaine (voir deploiement/INSTALLER.md).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Sauvegarde de la base du scanner")
    p.add_argument("--jours", type=int, default=14,
                   help="duree de conservation en jours (defaut 14)")
    return sauvegarder(p.parse_args().jours)


if __name__ == "__main__":
    raise SystemExit(main())
