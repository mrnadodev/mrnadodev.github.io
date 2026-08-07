#!/usr/bin/env python3
"""Sauvegarde complete de la base Supabase vers des fichiers JSON locaux.

POURQUOI CE SCRIPT
    Sur le plan gratuit, Supabase ne fait AUCUNE sauvegarde. Les sauvegardes
    quotidiennes arrivent avec le plan Pro (25 $/mois) ; le Point-in-Time
    Recovery est un supplement a 100 $/mois, disproportionne au stade actuel.
    En attendant que le chiffre d'affaires justifie le plan Pro, ce script
    donne l'essentiel : une copie datee, chez vous, de toutes vos donnees.

CE QU'IL SAUVEGARDE
    Les donnees des tables (profils, paris, caisse, signaux, messages,
    paiements...). Il ne sauvegarde PAS le schema, ni les politiques RLS,
    ni les fonctions : celles-ci vivent deja dans les fichiers .sql du
    depot, qui sont votre veritable sauvegarde de structure.

UTILISATION
    1. Recuperez la cle service_role :
         Supabase - Settings - API - service_role (secret)
       Cette cle contourne toute la RLS. Elle ne doit JAMAIS entrer dans le
       depot ni dans le navigateur.

    2. Depuis le dossier du projet :
         export SUPABASE_URL="https://xxxx.supabase.co"
         export SUPABASE_SERVICE_ROLE_KEY="eyJ..."
         python outils/sauvegarde_supabase.py

       Sous PowerShell :
         $env:SUPABASE_URL="https://xxxx.supabase.co"
         $env:SUPABASE_SERVICE_ROLE_KEY="eyJ..."
         python outils\\sauvegarde_supabase.py

    3. Les fichiers arrivent dans ~/nadoedge-sauvegardes/AAAA-MM-JJ-HHMM/

A FAIRE UNE FOIS PAR SEMAINE, au minimum. Planificateur de taches Windows :
    Declencheur hebdomadaire - Action : python, arguments : le chemin de ce
    fichier, avec les deux variables definies dans l'environnement systeme.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Tables sauvegardees. Une table absente est signalee mais n'interrompt rien :
# selon les migrations executees, certaines n'existent pas encore.
TABLES = [
    "profiles",
    "bets",
    "bankroll",
    "signals",
    "signals_audit",
    "messages",
    "payment_requests",
    "payment_channels",
    "app_settings",
    "sponsors",
    "site_content",
    "trial_grants",
]

PAGE = 1000          # Supabase plafonne les reponses ; on pagine.
GARDER = 8           # nombre de sauvegardes conservees (les plus anciennes sont effacees)


def _config() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not url or not key:
        print(
            "Il manque la configuration.\n\n"
            "  SUPABASE_URL              = https://xxxx.supabase.co\n"
            "  SUPABASE_SERVICE_ROLE_KEY = la cle service_role (Settings - API)\n\n"
            "Definissez ces deux variables d'environnement puis relancez.\n"
            "N'ecrivez jamais la cle service_role dans un fichier du depot.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url, key


def _aspirer(client: httpx.Client, url: str, table: str) -> list[dict] | None:
    """Recupere toutes les lignes d'une table, page par page.

    Retourne None si la table n'existe pas (ce n'est pas une erreur : le
    projet n'a peut-etre pas encore recu toutes les migrations).
    """
    lignes: list[dict] = []
    depart = 0
    while True:
        r = client.get(
            f"{url}/rest/v1/{table}",
            params={"select": "*", "limit": PAGE, "offset": depart},
        )
        if r.status_code == 404 or (
            r.status_code == 400 and "does not exist" in r.text
        ):
            return None
        r.raise_for_status()
        lot = r.json()
        lignes.extend(lot)
        if len(lot) < PAGE:
            return lignes
        depart += PAGE


def _purger(racine: Path) -> None:
    """Ne garde que les GARDER sauvegardes les plus recentes."""
    dossiers = sorted(
        (d for d in racine.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )
    for vieux in dossiers[GARDER:]:
        for f in vieux.iterdir():
            f.unlink()
        vieux.rmdir()
        print(f"  purge : {vieux.name}")


def main() -> int:
    url, key = _config()
    horodatage = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    racine = Path.home() / "nadoedge-sauvegardes"
    dossier = racine / horodatage
    dossier.mkdir(parents=True, exist_ok=True)

    entetes = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    total = 0
    absentes: list[str] = []
    print(f"Sauvegarde vers {dossier}\n")

    with httpx.Client(headers=entetes, timeout=60.0) as client:
        for table in TABLES:
            try:
                lignes = _aspirer(client, url, table)
            except httpx.HTTPStatusError as e:
                print(f"  {table:20} ECHEC ({e.response.status_code}) — {e.response.text[:80]}")
                continue
            if lignes is None:
                absentes.append(table)
                continue
            (dossier / f"{table}.json").write_text(
                json.dumps(lignes, ensure_ascii=False, indent=1, default=str),
                encoding="utf-8",
            )
            total += len(lignes)
            print(f"  {table:20} {len(lignes):6} ligne(s)")

    (dossier / "_resume.json").write_text(
        json.dumps(
            {
                "date": datetime.now(timezone.utc).isoformat(),
                "lignes_total": total,
                "tables_absentes": absentes,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    if absentes:
        print(f"\n  tables absentes (migrations non executees) : {', '.join(absentes)}")
    print(f"\n{total} ligne(s) sauvegardee(s) dans {dossier}")

    _purger(racine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
