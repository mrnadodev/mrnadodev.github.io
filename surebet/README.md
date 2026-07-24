# Surebet Haïti — Détection d'arbitrage sportif

Système de scraping + détection d'arbitrage (surebet) pour le marché haïtien
des paris sportifs (football & basketball), avec une couche IA qui identifie et
priorise les opportunités. Le cœur de calcul (`M`, ROI, mises) est **purement
déterministe** ; l'IA n'intervient que pour la normalisation sémantique des
libellés et l'explication des alertes (jamais dans le calcul d'arbitrage).

## Orientation pré-match

Le système cible **l'arbitrage pré-match** (matchs à venir), pas le jeu en
direct (in-play) :
- 1xBet interroge le feed `LineFeed` (pré-match) ; Golcash utilise
  `game_type=0` ; Paryaj Pam les événements à venir ; Paryaj Lakay la page
  `/sports`. Vérifié live : les 3 books à API rapide ne renvoient que des coups
  d'envoi **futurs** (0 match déjà commencé).
- Filtre de garantie : le scan et l'orchestrateur écartent tout match dont le
  coup d'envoi est passé (`prematch_only`), pour qu'un match en cours coté en
  « live » chez un book ne fausse pas la comparaison avec un autre resté en
  pré-match. Le `--dry-run` désactive ce filtre (fixtures aux dates figées).

## Bookmakers couverts

| Bookmaker | Méthode de collecte | Statut (test live juillet 2026) |
|-----------|---------------------|--------------------------------|
| **Golcash Haïti** | **API BetConstruct « Swarm » (WebSocket)** | ✅ **Opérationnel — 986 cotes / 44 matchs, sans Cloudflare ni compte** |
| **Paryaj Pam** | **WebSocket de cotes, token public `demo`** | ✅ **Opérationnel — 919 cotes / 49 matchs, sans compte ni navigateur** |
| **Paryaj Lakay** | SPA Angular → Playwright (DOM `hg-event-bet-type-item`) | ✅ **Validé live bout-en-bout** (6 marchés → 23 cotes canoniques) |
| **1xBet Haïti** | **API `service-api/LineFeed` via empreinte TLS Chrome** | ✅ **Opérationnel — 518 cotes / 50 matchs, sans navigateur ni frais** |

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

### Pièges d'appariement relevés en live

Cinq faux appariements détectés sur des données réelles, chacun capable de
fabriquer un surebet fantôme. Tous sont désormais bloqués et couverts par des
tests de non-régression :

| Piège | Symptôme | Traitement |
|---|---|---|
| **Variantes promo** (Paryaj Lakay) | Un même match expose « Résultat du match », « … **2UP** », « … (remboursé si nul) », « … (remboursé si X gagne) » — tous matchent `Résultat du match` et `1`/`X`/`2` | **exclues** : leurs règles de paiement diffèrent entre elles, donc elles ne sont équivalentes à rien |
| **Double Chance** (1xBet `G=8`) | Marge mesurée à **119 %** : les issues 1X / 12 / X2 se recouvrent | groupe exclu du mapping |
| **Périodes** (Paryaj Pam, Golcash) | Le même type de marché sert le temps réglementaire et les mi-temps | suffixes `_1h` / `_2h` ; période inconnue = marché écarté |
| **Variantes Team1/Team2** | « tirs équipe A » et « tirs équipe B » partagent le `market_type` | `team_scope` obligatoire (`home`/`away`) |
| **Équipes U-23 / réserve / féminine** | « Eltham Redbacks U-23 » et « Eltham Redbacks » matchent à **88** (> seuil 85) — deux matchs différents | niveau d'équipe vérifié **avant** la similarité |

#### Le faux surebet qui a coûté une leçon

La mesure de corrélation a détecté un surebet à **`M = 0,9458`, ROI +5,73 %**.
Vérification faite, il était **entièrement fictif** :

| Source | home | draw | away |
|---|---|---|---|
| Paryaj Lakay | 1.34 | 4.5 | 5.0 |
| Paryaj Pam **U-23** | 1.37 | 4.79 | 5.72 | ← le vrai correspondant |
| Paryaj Pam senior | 1.91 | 3.69 | 3.15 | ← apparié à tort |

Paryaj Lakay affichait le match **U-23** (coup d'envoi 08:15) ; le matcher flou
l'a apparié au match **senior** (10:30). Miser sur cette « opportunité » aurait
signifié miser sur **deux matchs différents**.

`teams.py` vérifie désormais le niveau d'équipe (`squad_marker` : jeunes /
réserve / féminine) **avant** toute comparaison de similarité — dans
`teams_match` comme dans `best_team_match`.

> Le pipeline de production utilise `match_id` (hachage exact), qui distinguait
> déjà ces deux matchs ; le faux positif venait du script de mesure. Mais la
> mission impose le matching flou (seuil 85) pour réconcilier les équipes entre
> bookmakers — sans ce garde-fou, la faille se serait déclenchée en production.

> Signe d'alerte utile : une marge implicite aberrante. Un « 1X2 » à `M ≈ 1,80`
> n'est pas un 1X2 — c'est un marché mal apparié (double chance ou variante
> promo). Le `scorer` traite d'ailleurs un ROI > 25 % comme un drapeau rouge
> pour cette raison (§6.3).

### Réconciliation floue des matchs entre bookmakers

`arbitrage/reconcile.py` relie les cotes du même match réel quand les books
nomment les équipes différemment (« FC Arges » ↔ « Arges »). Sans cela, le
`match_id` (hash exact) les sépare et elles ne se combinent jamais.

- regroupement par (sport, jour) puis fusion des paires d'équipes jugées
  identiques par `teams_similar` (token_set_ratio, seuil 85) ;
- garde-fous conservés : niveau d'équipe (U-23/réserve/féminine) et orientation
  domicile/extérieur (une inversion changerait les sélections) ;
- **mesuré en live : matchs cross-book 16 → 46** (×2,9), 37 `match_id` fusionnés.

Appliquée dans le scan du dashboard et dans `Scout.evaluate`.

### FunBets Paryaj Lakay (paris boostés)

La section « FunBet » de Paryaj Lakay (`/sports/manual-odds-boosts`) propose des
**paris combinés boostés** à cote gonflée (15, 20, 45, 130…), du type
« X gagne & les deux marquent & chaque équipe 6 corners ou + ». Vous les
combinez manuellement avec 1xBet pour des surebets à fort pourcentage.

Pipeline (`surebet/funbet/`) :
- **`scrape.py`** — extraction DOM (`.manual-odds-boost` → `.manual-odds-with-event-item`,
  `.odds-name` + `.value`) ; **12 FunBets lus en live**.
- **`parser.py`** — chaque libellé (un ET de conditions) est découpé en
  conditions élémentaires : victoire, BTTS, seuils (corners/tirs/tirs cadrés
  ≥ N → Over N−0.5), par équipe ou « chaque équipe ». Les accents sont
  normalisés (« tirs cadrés »).
- **`pricing.py`** — chaque condition est chiffrée depuis les cotes 1xBet ;
  prix juste = produit des cotes (indépendance). Si la cote boostée dépasse ce
  prix, c'est un **edge positif**. **Honnêteté** : on ne chiffre que ce qu'on
  trouve chez 1xBet ; si une condition n'est pas chiffrable, la valuation est
  marquée incomplète et **aucun edge n'est annoncé** — les jambes chiffrables
  restent affichées pour le hedge manuel.

**Marchés de niche 1xBet** (`scrapers/xbet_stats.py`) — pour chiffrer les
conditions corners/tirs des FunBets, le scraper 1xBet interroge son feed
par-événement (`GetGameZip`). Les statistiques y sont des **sous-jeux** nommés
(« Corners », « Tirs Cadrés », « Fautes », « Cartons jaunes », « Tacles »,
« Dégagements de but », « Sauvetages », « Contrôles VAR », « Hors-jeu »,
« Touches »), chacun réutilisant la convention standard `G=17` (total) /
`G=15`/`G=62` (par équipe), `T=9/10/11/12/13/14` (Over/Under). Récupéré
uniquement pour les matchs des FunBets (regroupés par match) afin de respecter
les rate-limits. « 8 corners ou + » → Over 7.5, chiffré à sa cote 1xBet réelle.

Quand toutes les conditions d'une FunBet sont ainsi chiffrables, l'**edge
complet** est calculé et affiché ; sinon la valuation reste partielle (jambes
connues affichées, reste signalé). Le pricing profond est activable via
`/api/funbets?deep=true` (défaut).

### Couverture des marchés de niche par bookmaker

Corners, tirs, tirs cadrés, fautes, tacles, cartons, dégagements, arrêts, VAR,
hors-jeu, touches — état réel constaté en live (juillet 2026) :

| Marché | Paryaj Pam | 1xBet | Paryaj Lakay | Golcash |
|---|---|---|---|---|
| Corners | ✅ | ✅ (par événement) | ✅ (« N ou + ») | ✅ |
| Tirs cadrés | ✅ | ✅ | ✅ | ❌ |
| Tirs | ✅ | ✅ | selon match | ❌ |
| Fautes | ✅ | ✅ | selon match | ❌ |
| Tacles | ✅ | ✅ | selon match | ❌ |
| Cartons | ✅ | ✅ | selon match | ❌ |
| Dégagements | ✅ | ✅ | selon match | ❌ |
| Arrêts gardien | ✅ | ✅ | selon match | ❌ |
| Hors-jeu | ✅ | ✅ | selon match | ❌ |
| Touches | ✅ | ✅ | selon match | ❌ |
| VAR | ❌ | ✅ | ❌ | ❌ |

- **Paryaj Pam** : 40+ types déjà mappés (`pamws.py`) — tout sauf VAR, que le
  book n'offre pas. **Reconnaissance dynamique** : si l'opérateur ajoute un
  marché avec un `tp` non mappé, `market_from_name` le reconnaît par son nom
  (`CornersTotal`, `YellowCardsTeam1Total`… et `VARTotal` s'il est ajouté).
- **1xBet** : tous via le feed par-événement (`xbet_stats.py`), VAR compris.
- **Paryaj Lakay** : format spécifique **« N ou + »** (« 5 ou + » = Over 4.5),
  désormais reconnu par `markets.py`. Vérifié live : 13 cotes `corners_team`
  captées sur un match. La profondeur des marchés de niche varie selon le match.
- **Golcash** : son feed BetConstruct ne propose aujourd'hui **que les corners**
  au-delà des buts. **Mais reconnaissance dynamique** : le scraper demande
  désormais *tous* les marchés (plus de liste blanche figée) et `resolve_swarm_market`
  reconnaît par motif les noms BetConstruct (`{Prefix}OverUnder`,
  `HomeTeam{Prefix}OverUnder`…). **Si Golcash ajoute cartons/fautes/tirs sur un
  match (ex. Premier League), ils sont captés automatiquement, sans modifier le
  code** — `YellowCardsOverUnder` → `cards_total`, `FoulsOverUnder` →
  `fouls_total`, etc. (handicap / odd-even / 1x2 correctement ignorés).

### Couverture des marchés de niche (Paryaj Pam / 1xBet, détail)

Les marchés de niche sont **systématiquement moins margés** que le 1X2, donc
c'est là que l'arbitrage est réaliste :

| Marché | Golcash | Paryaj Pam |
|---|---|---|
| `1x2` | 12,60 % | 9,98 % |
| `goals_total` | 10,26 % | **7,73 %** (min **3,41 %**) |
| `btts` | 10,27 % | 8,79 % |

Le mapping couvre donc les deux familles exigées par la mission (§2) :

- **Paryaj Pam** — 40+ types mappés : corners, cartons, fautes, tirs, tirs
  cadrés, hors-jeu, tacles, arrêts, touches, dégagements (totaux, par équipe et
  1X2). L'exemple §5.4 (« Tirs total Ghana 7.5 ») correspond aux types 132/133
  (`ShotsAllTeam1Total` / `ShotsAllTeam2Total`).
- **Golcash** — types réels relevés sur le flux : `CornersOverUnder`,
  `HomeTeamCornersOverUnder`, `TeamWithMostCornersWithDraw`, variantes mi-temps…

**Deux paramètres décisifs, calibrés en live :**

- `mcount=200` — les marchés de niche sont classés *après* les marchés
  principaux. Avec `mcount=60` : 10 types, aucun marché de niche. Avec
  `mcount=200` : 43 types, corners inclus, sur les matchs majeurs (MLS,
  Liga Profesional…). Les petites ligues n'offrent pas ces marchés.
- `count=500` — voir plus haut (couverture du catalogue).

Résultat de l'extension : Golcash passe de 986 à **2816 cotes** (3 → 15 types),
Paryaj Pam à **11 097 cotes** (16 types), et le nombre de marchés partagés entre
les deux books sur les matchs communs passe de 3 à **13**.

> Malgré cette couverture, aucun surebet n'apparaît entre ces deux books : la
> meilleure combinaison cross-book atteint `M = 1,0832` (−7,68 %). La corrélation
> des cotes, et non la couverture des marchés, est le facteur limitant.

### 1xBet débloqué — l'empreinte TLS, pas le navigateur

Cloudflare protège `/service-api/` et renvoyait un `403 "Just a moment..."` à
`httpx` — **et aussi à un Chromium headless piloté par Playwright**, dont même
les requêtes natives du site échouaient (9 requêtes `/service-api/*` sur 9).

Le facteur discriminant n'était pas le navigateur mais l'**empreinte TLS** :
Cloudflare identifie le client par son handshake (JA3), et la pile TLS de Python
est immédiatement reconnaissable comme non-navigateur.

`curl_cffi` avec `impersonate="chrome"` reproduit le handshake exact de Chrome.
Cloudflare laisse alors passer — **sans navigateur, sans proxy, sans service
payant**. Restaient trois paramètres à caler sur le flux réel :

| Élément | Valeur correcte | Symptôme si faux |
|---|---|---|
| Route | `/service-api/LineFeed/Get1x2_VZip` | `404 Fail route` |
| Paramètre sport | `sports=` | `406 NotAcceptable` |
| **Partenaire** | **`partner=151`** | `406 NotAcceptable` |
| En-tête | `x-svc-source: __V3_HOST_APP__` | `406 NotAcceptable` |

Les couples `(G, T)` du flux ont été validés par **cohérence de marge** sur
50 matchs réels : `G=1` 1X2 (9,4 %), `G=17` totaux (8,1 %), `G=15`/`G=62` totaux
par équipe (8,3 % / 8,5 %), `G=19` BTTS (8,8 %).

> **`G=8` est volontairement exclu.** Sa « marge » mesurée atteint **119 %** —
> c'est la Double Chance, dont les trois issues (1X / 12 / X2) se recouvrent. La
> traiter comme un marché à 3 issues fabriquerait des arbitrages fantômes.

L'orientation des totaux par équipe a été fixée par un cas extrême
(Timor oriental–Viêt-Nam, 1X2 à 40.00/1.02) : l'équipe domicile faible cote 3.90
sur « plus de 0.5 but », la dominante 1.60 sur « plus de 3.5 » — ce qui identifie
`G=15` comme domicile et `G=62` comme extérieur sans ambiguïté.

**1xBet est le book à cotation la plus serrée** : marge 1X2 minimale mesurée à
**5,25 %**, contre 12,6 % chez Golcash. C'est le partenaire d'arbitrage décisif.

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
