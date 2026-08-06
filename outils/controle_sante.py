#!/usr/bin/env python3
"""Controle de sante NADOEDGE : ce qui tombe en panne sans prevenir.

POURQUOI CE SCRIPT
    Deux pannes ont dure des jours sans que personne ne s'en apercoive :
      · le token Telegram du scanner, revoque — plus aucune alerte ;
      · quatre tests en echec depuis qu'une date figee est passee.
    Aucune des deux ne fait de bruit. Elles se voient seulement quand on
    va regarder. Ce script va regarder a votre place.

UTILISATION
    python outils/controle_sante.py

    Sans configuration, il verifie ce qu'il peut (base publique, tests).
    Avec les variables ci-dessous, il verifie tout :

      SUPABASE_URL              (sinon lu dans index.html)
      SUPABASE_ANON_KEY         (sinon lu dans index.html)
      SUPABASE_SERVICE_ROLE_KEY (facultatif : compte les signaux recents)

    Le token Telegram est lu dans surebet/.env.

A PLANIFIER une fois par jour. Code de sortie 1 si quelque chose cloche,
pour qu'un planificateur puisse alerter.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

RACINE = Path(__file__).resolve().parent.parent
OK, ALERTE, INFO = "  OK  ", " ALERTE", " info "
problemes: list[str] = []


def dire(etat: str, sujet: str, detail: str = "") -> None:
    print(f"[{etat}] {sujet}" + (f" : {detail}" if detail else ""))
    if etat == ALERTE:
        problemes.append(sujet)


def _depuis_index(cle: str) -> str:
    """Recupere une valeur de configuration depuis index.html."""
    try:
        txt = (RACINE / "index.html").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    m = re.search(rf'{cle}\s*:\s*"([^"]+)"', txt)
    return m.group(1) if m else ""


def verifier_base(url: str, key: str) -> None:
    if not url or not key:
        dire(INFO, "Supabase", "configuration introuvable, verification ignoree")
        return
    entetes = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    try:
        # Une vraie lecture : la table app_settings existe et la RLS la
        # protege. Un 200 prouve que l'API repond ET que le schema est la.
        r = httpx.get(f"{url}/rest/v1/app_settings", params={"select": "key", "limit": 1},
                      headers=entetes, timeout=15)
    except Exception as e:
        dire(ALERTE, "Supabase injoignable", str(e)[:70])
        return
    if r.status_code >= 500:
        dire(ALERTE, "Supabase en erreur", f"HTTP {r.status_code}")
        return
    dire(OK, "Supabase repond")

    # Horloge : c'est elle qui fausse l'age des signaux quand elle derive.
    try:
        t0 = datetime.now(timezone.utc)
        r = httpx.post(f"{url}/rest/v1/rpc/server_now", headers=entetes,
                       json={}, timeout=15)
        t1 = datetime.now(timezone.utc)
        if r.status_code != 200:
            dire(ALERTE, "server_now absente", "executez migration_horloge.sql")
        else:
            srv = datetime.fromisoformat(r.json().replace("Z", "+00:00"))
            ecart = ((t0 + (t1 - t0) / 2) - srv).total_seconds()
            if abs(ecart) > 60:
                dire(ALERTE, "Horloge de cette machine",
                     f"{ecart/60:+.1f} min sur le serveur : le scanner filtre mal les matchs")
            else:
                dire(OK, "Horloge de cette machine", f"{ecart:+.0f} s")
    except Exception as e:
        dire(ALERTE, "Verification de l'horloge", str(e)[:70])

    # Les fonctions installees par les migrations.
    for nom, corps, fichier in [
        ("signals_teaser", {}, "migration_landing.sql"),
        ("username_available", {"uname": "z"}, "securite_audit_2.sql"),
        ("metriques_resume", {}, "migration_metriques.sql"),
    ]:
        try:
            r = httpx.post(f"{url}/rest/v1/rpc/{nom}", headers=entetes,
                           json=corps, timeout=15)
            if r.status_code == 404:
                dire(ALERTE, f"Fonction {nom} absente", f"executez {fichier}")
            else:
                dire(OK, f"Fonction {nom}")
        except Exception as e:
            dire(ALERTE, f"Fonction {nom}", str(e)[:60])


def verifier_signaux(url: str) -> None:
    """Depuis combien de temps rien n'a ete publie ? Demande la cle service_role."""
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        dire(INFO, "Derniere publication",
             "definissez SUPABASE_SERVICE_ROLE_KEY pour verifier")
        return
    entetes = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        r = httpx.get(f"{url}/rest/v1/signals",
                      params={"select": "created_at", "order": "created_at.desc",
                              "limit": 1},
                      headers=entetes, timeout=15)
        r.raise_for_status()
        lignes = r.json()
        if not lignes:
            dire(ALERTE, "Aucun signal en base", "vos abonnes n'ont rien recu")
            return
        dernier = datetime.fromisoformat(lignes[0]["created_at"].replace("Z", "+00:00"))
        heures = (datetime.now(timezone.utc) - dernier).total_seconds() / 3600
        if heures > 48:
            dire(ALERTE, "Derniere publication",
                 f"il y a {heures/24:.1f} jour(s) : un abonne qui paie ne recoit rien")
        else:
            dire(OK, "Derniere publication", f"il y a {heures:.1f} h")
    except Exception as e:
        dire(ALERTE, "Lecture des signaux", str(e)[:70])


def verifier_telegram() -> None:
    """Le token revoque a coupe les alertes pendant des jours, en silence."""
    env = RACINE / "surebet" / ".env"
    if not env.exists():
        dire(INFO, "Telegram", "surebet/.env introuvable")
        return
    conf = dict(
        re.findall(r"^(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=(.*)$",
                   env.read_text(encoding="utf-8", errors="ignore"), re.M)
    )
    token = (conf.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (conf.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token:
        dire(ALERTE, "Telegram", "aucun token dans surebet/.env")
        return
    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
        if not r.get("ok"):
            dire(ALERTE, "Token Telegram refuse", str(r.get("description"))[:60])
            return
        dire(OK, "Token Telegram", "bot " + r["result"].get("username", "?"))
    except Exception as e:
        dire(ALERTE, "Telegram injoignable", str(e)[:70])
        return

    if not chat:
        dire(ALERTE, "Telegram", "aucun canal configure")
        return
    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getChat",
                      params={"chat_id": chat}, timeout=15).json()
        if not r.get("ok"):
            dire(ALERTE, "Canal Telegram inaccessible",
                 f"{chat} : {str(r.get('description'))[:50]}")
            return
        titre = r["result"].get("title", "?")
        # Droit de publier : sans lui, l'envoi echoue au moment ou ca compte.
        bot_id = token.split(":", 1)[0]
        m = httpx.get(f"https://api.telegram.org/bot{token}/getChatMember",
                      params={"chat_id": chat, "user_id": bot_id}, timeout=15).json()
        peut = m.get("ok") and m["result"].get("can_post_messages")
        if peut:
            dire(OK, "Canal Telegram", f"{titre} : publication autorisee")
        else:
            dire(ALERTE, "Canal Telegram", f"{titre} : le bot ne peut PAS publier")
    except Exception as e:
        dire(ALERTE, "Canal Telegram", str(e)[:70])


def verifier_tests() -> None:
    """Quatre tests etaient rouges depuis deux semaines sans que ca se voie."""
    try:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "surebet/tests/", "-q", "--no-header"],
            cwd=RACINE, capture_output=True, text=True, timeout=300,
        )
    except Exception as e:
        dire(INFO, "Tests", f"non executables ici ({str(e)[:40]})")
        return
    sortie = (p.stdout or "") + (p.stderr or "")
    resume = next((l for l in reversed(sortie.splitlines())
                   if "passed" in l or "failed" in l or "error" in l), "")
    if p.returncode == 0:
        dire(OK, "Tests du scanner", resume.strip()[:60])
    else:
        dire(ALERTE, "Tests du scanner", resume.strip()[:70])


def main() -> int:
    print(f"Controle de sante NADOEDGE - "
          f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    url = (os.environ.get("SUPABASE_URL") or _depuis_index("SUPABASE_URL")).rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY") or _depuis_index("SUPABASE_ANON_KEY")

    verifier_base(url, key)
    verifier_signaux(url)
    verifier_telegram()
    verifier_tests()

    print()
    if problemes:
        print(f"{len(problemes)} point(s) a corriger :")
        for p in problemes:
            print(f"  - {p}")
        return 1
    print("Tout est en ordre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
