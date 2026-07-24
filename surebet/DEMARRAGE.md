# Démarrage rapide — usage quotidien

## Installer le lanceur sur le Bureau (une seule fois)

1. Ouvrir le dossier `surebet` de ce projet.
2. Clic droit sur **`Surebet.bat`** → **Envoyer vers** → **Bureau (créer un raccourci)**.
3. Renommer le raccourci « Surebet » si vous le souhaitez.

Le premier lancement installe automatiquement les dépendances (2–3 minutes).
Les suivants démarrent en quelques secondes.

## Utilisation

**Double-cliquer le raccourci.** Le programme :

1. interroge les 4 bookmakers (≈ 60–90 s, Paryaj Lakay étant le plus lent) ;
2. affiche un rapport dans la console ;
3. ouvre le tableau de bord dans votre navigateur ;
4. écrit un `surebet_opportunites.xlsx` si des opportunités existent.

Exemple de rapport :

```
==================================================================
  SCAN SUREBET — 24/07/2026 07:30 — football
==================================================================
  [OK]     Golcash          2858 cotes
  [OK]     Paryaj Pam      11117 cotes
  [OK]     1xBet             522 cotes
  [OK]     Paryaj Lakay      612 cotes

  Total collecte : 15109 cotes
------------------------------------------------------------------
  Aucune opportunite d'arbitrage pour le moment.
==================================================================
```

Fermer la fenêtre pour tout arrêter.

## À quoi s'attendre, honnêtement

**La plupart des scans ne trouveront rien.** C'est normal et attendu :

- une fenêtre d'arbitrage dure quelques **minutes** ;
- un scan unique le matin a peu de chances de tomber dedans ;
- sur le marché haïtien, les marges des books sont élevées (5–13 %).

Un scan qui ne trouve rien **n'est pas une panne** — c'est le résultat correct.
Ce que le scan garantit, c'est que si une opportunité existe à cet instant,
elle est détectée, chiffrée et vérifiée.

Pour réellement attraper les fenêtres, laissez tourner la surveillance continue :

```bash
python -m surebet.main --collector
```

## Alertes Telegram (optionnel)

Sans configuration, aucune alerte n'est envoyée (le scan affiche simplement le
rapport). Pour recevoir les opportunités sur Telegram :

1. Créer un bot via [@BotFather](https://t.me/BotFather) → il donne un token.
2. Écrire à votre bot, puis récupérer votre `chat_id`.
3. Copier `.env.example` en `.env` et renseigner :

```
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id
```

Une alerte part dès qu'une opportunité atteint **ROI ≥ 2 %** et **score ≥ 70**.

## Avant de miser de l'argent réel

Le système est un outil d'aide à la décision, pas une garantie :

- **Vérifiez toujours** que les deux paris portent sur le **même match** et le
  **même marché** avant de miser. Cinq types de faux appariements ont déjà été
  identifiés et bloqués (voir README), mais un bookmaker peut en introduire un
  nouveau à tout moment.
- Une cote peut changer entre la détection et votre mise.
- L'arbitrage entraîne des **limitations de compte** chez les bookmakers.
- Ce projet ne constitue pas un conseil financier.

## En cas de problème

| Symptôme | Cause probable |
|---|---|
| « Python est introuvable » | Installer Python 3.11+ en cochant « Add Python to PATH » |
| Un book en `[ECHEC]` | Site momentanément indisponible ou structure modifiée — les autres continuent |
| Scan très lent (> 3 min) | Paryaj Lakay charge ses pages une par une (Playwright) |
| Aucune alerte Telegram | `.env` absent ou non renseigné |
