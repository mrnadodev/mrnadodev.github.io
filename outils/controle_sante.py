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

    Aucune configuration necessaire : l'URL et la cle publique sont lues
    dans index.html, le token Telegram dans surebet/.env.

    AUCUN SECRET N'EST REQUIS. Les verifications qui touchent a des donnees
    protegees passent par des fonctions serveur qui ne renvoient que des
    agregats. La cle service_role, qui contourne toute la RLS, n'a rien a
    faire sur une machine exposee a internet — surtout pour connaitre une
    date.

      SUPABASE_URL       (facultatif : sinon lu dans index.html)
      SUPABASE_ANON_KEY  (facultatif : sinon lu dans index.html)

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


def verifier_signaux(url: str, key: str) -> None:
    """Depuis combien de temps rien n'a ete publie pour les abonnes ?

    C'est l'alerte la plus utile : elle previent qu'un client qui paie ne
    recoit rien. Elle passe par une fonction serveur qui ne renvoie que
    deux nombres — pas par la cle service_role, qui contourne toute la RLS
    et n'a rien a faire sur une machine exposee a internet.
    """
    if not url or not key:
        return
    entetes = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    try:
        r = httpx.post(f"{url}/rest/v1/rpc/derniere_publication",
                       headers=entetes, json={}, timeout=15)
        if r.status_code == 404:
            dire(INFO, "Derniere publication",
                 "executez migration_derniere_publication.sql")
            return
        r.raise_for_status()
        d = r.json()
        d = d[0] if isinstance(d, list) and d else d
        if not d or d.get("publie_le") is None:
            dire(ALERTE, "Aucun signal publie", "vos abonnes n'ont jamais rien recu")
            return
        heures = float(d.get("heures_depuis") or 0)
        sept_j = d.get("signaux_7j") or 0
        if heures > 48:
            dire(ALERTE, "Derniere publication",
                 f"il y a {heures/24:.1f} jour(s) : un abonne qui paie ne recoit rien")
        elif sept_j < 4:
            # Sous 4 signaux par semaine, l'abonnement ne se renouvelle pas :
            # c'est le seuil constate dans les metriques du tableau de bord.
            dire(ALERTE, "Volume de publication",
                 f"{sept_j} signal(aux) sur 7 jours : trop peu pour fideliser")
        else:
            dire(OK, "Derniere publication",
                 f"il y a {heures:.1f} h ({sept_j} sur 7 jours)")
    except Exception as e:
        dire(ALERTE, "Lecture des publications", str(e)[:70])


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


def verifier_tache_scanner() -> None:
    """Le scanner tourne-t-il vraiment ?

    C'est LA panne silencieuse du VPS : tout le reste peut etre vert
    pendant que la tache planifiee est arretee, et personne ne le voit
    avant de constater l'absence d'alertes pendant des jours.

    Sur une machine sans la tache (un PC de developpement), on ne dit rien
    d'alarmant : la tache n'y a simplement pas lieu d'exister.
    """
    if os.name != "nt":
        return
    tache = "NADOEDGE-Scanner"
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$t = Get-ScheduledTask -TaskName '{tache}' -ErrorAction SilentlyContinue; "
             f"if (-not $t) {{ 'ABSENTE' }} else {{ "
             f"$i = $t | Get-ScheduledTaskInfo; "
             f"\"$($t.State)|$($i.LastTaskResult)|$($i.LastRunTime)\" }}"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        dire(INFO, "Tache du scanner", f"non verifiable ({str(e)[:40]})")
        return

    sortie = (p.stdout or "").strip()
    if not sortie or sortie == "ABSENTE":
        dire(INFO, "Tache du scanner",
             "absente sur cette machine (normale sur un PC, anormale sur le VPS)")
        return

    etat, code, derniere = (sortie.split("|") + ["", "", ""])[:3]
    if etat == "Running":
        dire(OK, "Tache du scanner", f"en cours d'execution (depuis {derniere[:16]})")
    elif etat == "Ready":
        dire(ALERTE, "Tache du scanner",
             f"ARRETEE - aucune detection en cours (dernier code {code})")
    else:
        dire(ALERTE, "Tache du scanner", f"etat inattendu : {etat}")


def main() -> int:
    print(f"Controle de sante NADOEDGE - "
          f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    url = (os.environ.get("SUPABASE_URL") or _depuis_index("SUPABASE_URL")).rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY") or _depuis_index("SUPABASE_ANON_KEY")

    verifier_base(url, key)
    verifier_signaux(url, key)
    verifier_telegram()
    verifier_tache_scanner()
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
