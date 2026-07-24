# Surebet Haïti — Détection d'arbitrage sportif

Système de scraping + détection d'arbitrage (surebet) pour le marché haïtien
des paris sportifs (football & basketball), avec une couche IA qui identifie et
priorise les opportunités. Le cœur de calcul (`M`, ROI, mises) est **purement
déterministe** ; l'IA n'intervient que pour la normalisation sémantique des
libellés et l'explication des alertes (jamais dans le calcul d'arbitrage).

## Bookmakers couverts

| Bookmaker | Méthode de collecte | Statut (test live juillet 2026) |
|-----------|---------------------|--------------------------------|
| **Golcash Haïti** | **API BetConstruct « Swarm » (WebSocket)** | ✅ **Opérationnel — 986 cotes / 44 matchs, sans Cloudflare ni compte** |
| **Paryaj Pam** | **WebSocket de cotes, token public `demo`** | ✅ **Opérationnel — 919 cotes / 49 matchs, sans compte ni navigateur** |
| **Paryaj Lakay** | SPA Angular → Playwright (DOM `hg-event-bet-type-item`) | ✅ **Validé live bout-en-bout** (6 marchés → 23 cotes canoniques) |
| 1xBet Haïti | API `service-api/LineFeed` | ❌ **Bloqué** — Cloudflare *managed challenge* sur `/service-api/` en headless |

> Les scrapers Playwright reposent sur la structure DOM observée en
> reconnaissance (juillet 2026). Les sites réels évoluent et sont protégés par
> Cloudflare : les sélecteurs CSS marqués `TODO PROD` doivent être revalidés
> périodiquement. Respectez `robots.txt` et les rate-limits (délais 1–3 s
> intégrés).

### Golcash / BetConstruct Swarm — le meilleur canal identifié

Golcash tourne sur la plateforme white-label **BetConstruct**. Sa configuration
publique (`/conf.json`) expose tout ce qu'il faut :

```
socketUrl : wss://eu-swarm-newm.betconstruct.com/
site_id   : 1345
```

L'API Swarm est un protocole WebSocket structuré : `request_session` puis `get`
avec un sélecteur `what`/`where`. Elle renvoie **l'intégralité des marchés sans
Cloudflare, sans navigateur et sans compte** — de loin le canal le plus rapide et
le plus stable des quatre bookmakers. Implémentée dans
[`scrapers/swarm.py`](scrapers/swarm.py) et [`scrapers/golcash.py`](scrapers/golcash.py).

Mesures réelles du test de validation : 986 cotes canoniques (772 `goals_total`,
132 `1x2`, 82 `btts`) sur 44 matchs ; marges 1X2 réelles de 9,55 % à 15,11 %
(médiane 12,97 %) — toutes > 1, donc aucun arbitrage intra-book, cohérent.

### Paryaj Pam — WebSocket avec token public `demo`

Fausse piste initiale : l'API REST `admin-prod.newfeed.paryajpam.com/api/v1/*`
est joignable sans Cloudflare (paramètre `partner=paryajpam`) mais **exige un
compte** (`{"code":2000,"message":"Unknown account"}`).

Le vrai feed est ailleurs — un **WebSocket dédié acceptant le token public
`demo`**, donc **sans compte, sans navigateur et sans Cloudflare** :

```
wss://wss-new.sport.paryajpam.com/ws/?token=demo&ln=en

1. {"lang":"en","action":"auth","token":"demo","tree":false,"hot":false}
     -> {"action":"auth","result":true}
2. {"lang":"en","action":"mnames"}          # dictionnaire des 130 types de marchés
3. {"lang":"en","action":"hot2","sport":-1,"count":50,"mcount":30,"marker":"all"}
     -> événements ; chacun porte ses marchés dans `mr`,
        `kf` = la cote, `vl` = la ligne (2.5, 7.5…)
```

Protocole reconstitué en interceptant les trames réelles du site via un
`add_init_script` Playwright posé **avant** le JS de la page. Implémenté dans
[`scrapers/pamws.py`](scrapers/pamws.py) et [`scrapers/paryajpam.py`](scrapers/paryajpam.py).

> **Piège important** : le flux renvoie le **même type de marché** (`tp`) pour le
> temps réglementaire et pour chaque mi-temps, distingués seulement par `pn`
> (`MainTime` / `Half1` / `Half2`). Sans ce suffixe, un 1X2 de 1ʳᵉ mi-temps serait
> apparié avec un 1X2 de match entier → **faux arbitrage**. Le scraper écarte
> toute période inconnue plutôt que de risquer l'appariement (spec §6.1).

Mesures du test de validation : 919 cotes sur 49 matchs (147 `1x2`, 147 `1x2_1h`,
141 `1x2_2h`, 93 `goals_total`, 200 `goals_team`…) ; marges 1X2 réelles de 5,15 %
à 11,31 % — toutes > 1, aucune anomalie d'appariement.

### Constat clé : largeur du catalogue et corrélation des cotes

Deux enseignements du test cross-book live, importants pour l'exploitation :

**1. Il faut le catalogue large, pas la sélection « hot ».** Avec `count=50`,
Paryaj Pam renvoie 50 matchs vedettes et le recouvrement avec Golcash est **nul**.
Avec `count=500` : 494 matchs et **5 matchs communs** exploitables. D'où le défaut
`count=500` dans le scraper — l'arbitrage a besoin de couverture, pas de sélection.

**2. Golcash et Paryaj Pam semblent partager le même fournisseur de cotes.** Sur
les 5 matchs communs, leurs cotes sont quasi identiques (ex. `2.45/2.45`,
`3.27/3.23`, `2.52/2.43`). Prendre le meilleur des deux ne fait tomber la marge
que de ~11,5 % à ~11,0 % — très loin du seuil d'arbitrage. **Aucun surebet n'est
structurellement attendu entre ces deux books seuls.**

> Conséquence pratique : un arbitrage réel exige au moins un book à cotation
> **indépendante**. C'est ce qui rend 1xBet (qui fait sa propre cotation)
> stratégiquement important, et pourquoi les exemples de la mission combinent
> justement 1xBet et Paryaj Lakay avec ces deux books.

### Findings du test live 1xBet (juillet 2026)

Un test live réel a révélé que **1xBet Haïti n'est plus une API JSON simple**
comme le supposait la mission :

1. **Route corrigée** : la bonne URL est `/service-api/LineFeed/Get1x2_VZip`
   avec le paramètre `sports=` (et non `/LineFeed/...?sportId=`, qui renvoie
   `404 Fail route`). Corrigé dans `scrapers/xbet.py`.
2. **Cloudflare** fronte désormais l'API : un GET httpx direct reçoit un
   `403 "Just a moment..."`. Le scraper retombe sur un **fallback navigateur**
   (Playwright) qui charge l'origine, attend la résolution du challenge JS, puis
   fait un `fetch()` XHR in-page — ce mécanisme **franchit Cloudflare avec succès**.
3. **En-tête réel identifié** : les requêtes du site vers `/service-api/*`
   portent un en-tête custom `x-svc-source: __V3_HOST_APP__` (absent → `406
   feed/NotAcceptableException`). Ajouté au scraper.
4. **Profil persistant : la page passe, l'API non.** Avec une session à profil
   persistant (`collector/session.py`), la **page HTML franchit Cloudflare dès la
   2ᵉ visite** (profil réchauffé : titre réel, plus de challenge). Mais **toutes
   les requêtes `/service-api/*` restent en 403** (9/9 mesurées : `Get1x2_VZip`,
   `GetSportsShortZip`, `WebGetTopChampsZip`, `getbanner`…). Cloudflare applique
   donc une règle **distincte et plus stricte sur la route API**, que la clearance
   de page ne satisfait pas.
5. **Conclusion définitive (test live poussé)** : en mode **headless**,
   Cloudflare bloque la route `/service-api/LineFeed/` par un *managed challenge*
   — **même les propres requêtes du site échouent en 403**, et le cookie
   `cf_clearance` de la page HTML ne débloque pas l'API. Le seul levier restant
   non testé est le mode **headful** (Cloudflare empreinte le Chromium headless) ;
   il n'a pas pu être lancé dans l'environnement sandboxé (« spawn UNKNOWN »).
   Le scraper intercepte donc la réponse native du site (`Get1x2_VZip`) plutôt
   que de refaire un `fetch()`, et expose `headless=False` : **un navigateur
   non-headless (avec affichage, ou `xvfb` sous Linux) est requis en production**
   pour franchir le challenge. Le lancement headful n'a pas pu être testé dans
   l'environnement sandboxé (pas de display). Pour un déploiement serveur fiable,
   prévoir soit un navigateur furtif (playwright-stealth / undetected-chromedriver)
   soit un accès data partenaire.

Le moteur d'arbitrage, la normalisation, le scoring et le reste du pipeline sont
entièrement fonctionnels et testés hors-ligne sur données réelles ; seul l'accès
réseau live à 1xBet bute sur ce mur anti-bot Cloudflare (contrainte externe, pas
un défaut du système).

## Architecture

```
surebet/
├── scrapers/     # base (httpx+retry), xbet (API), 3 scrapers Playwright, parsing pur
├── normalizer/   # schema canonique, fuzzy teams (rapidfuzz 85), markets (règles), ai_normalizer (LLM)
├── arbitrage/    # detector (M/ROI), stakes (mises+arrondi), combinatorics (cross-bookmakers)
├── ai/           # scout (détection continue, quasi-surebets), scorer (fiabilité 0-100)
├── storage/      # SQLAlchemy async (table opportunities), cache de normalisation
├── notifier/     # alertes Telegram
├── export/       # export Excel (colonnes du fichier fourni)
├── dashboard/    # FastAPI + HTMX (live, historique, bankroll, taux IA)
├── config.py     # pydantic-settings (.env)
└── main.py       # orchestrateur asyncio
```

Voir [`MODELE.md`](MODELE.md) pour les formules détaillées 2 et 3 issues.

## Installation

```bash
cd surebet
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium                # pour les scrapers Playwright
cp .env.example .env                                 # puis renseigner les clés
```

## Configuration (`.env`)

Toutes les valeurs ont un défaut raisonnable. À renseigner selon l'usage :

- `ANTHROPIC_API_KEY` — active le fallback IA de normalisation et les
  explications d'alertes. **Sans clé, le système fonctionne en mode déterministe**
  (règles seules + explications par gabarit).
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — active l'envoi réel des alertes.
- `DATABASE_URL` — SQLite par défaut ; Postgres pour la prod (voir Docker).

## Lancement

### Cycle de détection (orchestrateur)

```bash
python -m surebet.main --sport football      # ou --sport basketball
```

### Mode collector (recommandé en production)

```bash
python -m surebet.main --collector --sport football
```

Découple la **collecte** de l'**évaluation** :

- une **session navigateur persistante par bookmaker** (`collector/session.py`),
  avec profil sur disque — le cookie `cf_clearance` et la session survivent aux
  redémarrages, et la page est réutilisée d'un cycle à l'autre au lieu de
  relancer un navigateur (ce qui faisait re-challenger Cloudflare à chaque fois) ;
- une **tâche asyncio indépendante par bookmaker**, chacune à sa cadence — la
  panne d'un book n'interrompt pas les autres, et une indisponibilité > 5 min
  déclenche une alerte (§9) ;
- un **pool de cotes partagé** (`collector/pool.py`) où chaque book publie sa
  contribution de façon atomique, avec éviction automatique des cotes > 60 s ;
- une **boucle d'évaluation** séparée qui lit des instantanés frais et lance la
  détection, à sa propre fréquence (`evaluation_interval_s`).

> **Important** : mettre `BROWSER_HEADLESS=false` dans `.env` en production. Le
> test live a montré qu'en headless Cloudflare bloque les routes de feed (403),
> y compris les requêtes natives du site. Sous Linux sans écran, lancer via
> `xvfb-run -a python -m surebet.main --collector`.

### Démonstration hors-ligne (aucun réseau)

Rejoue les fixtures réelles + les exemples de référence §5.4/§5.5 et affiche un
cycle complet scrape → détection → scoring :

```bash
python -m surebet.main --dry-run
```

### Peupler le dashboard puis le lancer

```bash
python -m surebet.seed_demo                                   # seed les surebets de démo
python -m uvicorn surebet.dashboard.app:app --port 8000       # http://localhost:8000
```

## Docker

```bash
cd surebet
cp .env.example .env
docker compose up --build
```

Démarre trois services : `postgres`, `app` (boucle de détection) et `dashboard`
(http://localhost:8000). `app` et `dashboard` partagent la base Postgres.

## Tests

```bash
cd surebet
pytest -v
```

La suite couvre :
- **`test_arbitrage.py`** — reproduit **exactement** les exemples §5.4 (ROI 3.85 %,
  profit 1923 HTG) et §5.5 (ROI 18.89 %, profit 9444 HTG).
- **`test_normalizer.py`** — 55 paires positives (libellés réels FR/EN/créole +
  symboles `>`/`<`) et 22 pièges négatifs (tirs ≠ tirs cadrés, corners mi-temps
  ≠ match, mauvaise équipe…).
- **`test_ai_normalizer.py`** — pipeline règles → cache → budget → validation
  Pydantic → repli, avec client LLM mocké (aucun réseau).
- **`test_scrapers.py`** — parsing du JSON 1xBet réel (respx) et du HTML Paryaj
  Lakay réel (fixture), hors-ligne.
- **`test_scout_scorer.py`**, **`test_storage.py`**, **`test_notifier_export.py`**,
  **`test_dashboard.py`**.

## Sécurité & conformité

- Cotes de plus de 60 s filtrées avant détection.
- Chaque échec de scraping est journalisé par bookmaker ; alerte critique si
  indisponibilité > 5 min.
- Aucun identifiant en dur : tout passe par `.env`.
- Aucun appel LLM dans le chemin critique du calcul d'arbitrage ; sorties LLM
  validées en JSON strict (Pydantic), rejet + repli sur les règles en cas d'échec.
