# MODÈLE MATHÉMATIQUE — Détection de surebets 2 et 3 issues

Ce document détaille les formules implémentées dans `arbitrage/` (spec MISSION §5).
**Le calcul est purement déterministe et fait autorité** : la couche IA ne le
remplace jamais (spec MISSION §6.4).

## 1. Marge implicite combinée `M`

Pour un pari à `n` issues aux cotes `Cote_1 … Cote_n` (une par bookmaker,
issue distincte) :

```
M = Σ (1 / Cote_i)   pour i = 1..n
```

`M` est la somme des probabilités implicites. Une seule fonction générique
prend une liste de cotes, quel que soit `n` :

```python
def implied_margin(odds: list[float]) -> float:
    return sum(1.0 / o for o in odds)
```

- **`M < 1`** → **surebet** : profit garanti quelle que soit l'issue.
- **`M ≥ 1`** → pas d'opportunité.

## 2. ROI garanti

```
ROI% = (1/M − 1) × 100
```

## 3. Répartition des mises

La bankroll `B` est répartie pour que le **retour soit identique** quelle que
soit l'issue :

```
Mise_i = B / (Cote_i × M)
```

Propriétés vérifiées par les tests :
- `Σ Mise_i = B` (toute la bankroll est engagée),
- `Gain_i = Mise_i × Cote_i = B/M` — **constant** pour toute issue `i`.

## 4. Profit garanti

```
Profit         = B/M − B = B × (1/M − 1)
Balance_finale = Balance_initiale + Profit
```

## 5. Exemple validé — 2 issues (§5.4)

**Colombie vs Ghana — « Tirs total Ghana 7.5 »**
- Paryaj Pam, moins 7.5 → **2.16**
- Golcash, plus 7.5 → **2.00**

```
M      = 1/2.16 + 1/2.00 = 0.46296 + 0.50000 = 0.96296  < 1  ✓
ROI    = 1/0.96296 − 1 = 3.85 %
B      = 50 000 HTG
Mise_A = 50000 / (2.16 × 0.96296) = 24 038.46 HTG
Mise_B = 50000 / (2.00 × 0.96296) = 25 961.54 HTG
Gain   = 24 038.46 × 2.16 = 51 923 HTG   (identique sur l'autre issue)
Profit = 1 923 HTG
```

Reproduit exactement par `tests/test_arbitrage.py::test_colombie_ghana`.

## 6. Exemple de référence — 3 issues (§5.5)

**1X2, meilleures cotes agrégées sur 3 bookmakers**
- Domicile, Paryaj Lakay → **3.55**
- Nul, 1xBet → **3.90**
- Extérieur, Golcash → **3.30**

```
M      = 1/3.55 + 1/3.90 + 1/3.30 = 0.28169 + 0.25641 + 0.30303 = 0.84113  < 1  ✓
ROI    = 1/0.84113 − 1 = 18.89 %
B      = 50 000 HTG
Mise_1 = 50000 / (3.55 × 0.84113) = 16 744.73 HTG
Mise_N = 50000 / (3.90 × 0.84113) = 15 242.00 HTG
Mise_2 = 50000 / (3.30 × 0.84113) = 18 013.27 HTG
Gain   = 16 744.73 × 3.55 = 59 444 HTG   (identique sur les 3 issues)
Profit = 9 444 HTG
```

Reproduit par `tests/test_arbitrage.py::test_1x2_trois_books`.

> **Note sur les mises du texte de la mission.** Le texte §5.5 affiche
> 16 745.35 / 15 242.34 / 18 012.31 (profit 9 445), valeurs issues d'un arrondi
> intermédiaire de `M` dans le fichier Excel source (non fourni). En appliquant
> les formules exactes ci-dessus en pleine précision (`Mise_i = B/(Cote_i·M)`),
> on obtient 16 744.73 / 15 242.00 / 18 013.27 (somme exacte = 50 000, profit
> 9 443.8), **internement cohérentes** — c'est cette précision que l'implémentation
> retient. L'écart (< 1 HTG par mise) est un pur artefact d'arrondi de la source.

## 7. Arrondi réel (§5.6)

Les mises sont arrondies à l'entier (HTG). Après arrondi :
- on recalcule `min(Gain_i)` sur **toutes** les issues ;
- on n'alerte que si `min(Gain_i) > B` (le profit reste garanti malgré l'arrondi) ;
- on respecte les mises min/max de chaque bookmaker (`clamp_to_bookmaker_limits`).

Sur 3 issues, l'arrondi est plus sensible : un **ajustement résiduel** est
appliqué sur la mise de l'issue à la cote la plus élevée pour que
`Σ Mise_i = B` reste exact (`split_stakes(..., round_to=0)`).

## 8. Règles d'appariement (§4)

- **2 issues** : `match_id`, `market_type`, `line`, `team_scope` identiques ;
  `selection` opposée ; `bookmaker` différent.
- **3 issues** : `match_id` et `market_type` identiques ; les trois `selection`
  ∈ {home, draw, away} couvertes exactement une fois ; au moins deux bookmakers
  distincts. Pour chaque issue, la **cote maximale** disponible tous bookmakers
  confondus est retenue (`best_odds_per_outcome`, `best_three_way`).
