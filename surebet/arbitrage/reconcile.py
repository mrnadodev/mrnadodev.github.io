"""Reconciliation des matchs entre bookmakers par appariement flou d'equipes.

Probleme : chaque bookmaker nomme les equipes a sa maniere ("Manchester Utd"
vs "Man United", "FC Arges" vs "Arges"). Le `match_id` etant un hash exact des
noms normalises + jour, deux cotes du meme match reel chez deux books recoivent
des match_id differents et ne se combinent jamais.

Solution : regrouper les cotes par (sport, jour), puis fusionner les paires
d'equipes que le fuzzy matching (seuil 85, garde-fou U-23/reserve inclus) juge
identiques, en leur attribuant un match_id canonique commun.

Garde-fous (issus des tests live) :
- meme niveau d'equipe requis (Eltham U-23 != Eltham) via le garde-fou squad ;
- seule l'orientation domicile/exterieur identique est fusionnee : un match ou
  les books inversent domicile et exterieur inverserait aussi les selections
  (home <-> away), source de faux arbitrage — on ne le fusionne donc pas.

Limite connue : le seuil 85 rejette correctement les faux positifs proches
(Man City vs Man United = 81) mais laisse passer quelques abreviations
legitimes a la marge (ex. "Petrolul Ploiesti" vs "FC Petrolul" = 84). C'est le
compromis inherent au seuil impose par la mission ; en pratique deux books
nomment une equipe de facon assez coherente pour matcher.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from ..normalizer.schema import Odd
from ..normalizer.teams import DEFAULT_THRESHOLD, teams_similar


def _day_key(odd: Odd) -> str:
    return odd.start_time.strftime("%Y-%m-%d")


def reconcile_pool(pool: list[Odd], threshold: int = DEFAULT_THRESHOLD) -> list[Odd]:
    """Retourne un pool ou les cotes du meme match reel partagent un match_id.

    Les cotes deja regroupees par match_id exact restent groupees ; le fuzzy ne
    fait que fusionner des groupes distincts qui designent le meme match.
    """
    # 1) partir des groupes match_id exacts (un representant par groupe)
    groups: dict[str, list[Odd]] = defaultdict(list)
    for odd in pool:
        groups[odd.match_id].append(odd)

    representatives = {mid: odds[0] for mid, odds in groups.items()}

    # 2) clusteriser les match_id par (sport, jour) via fuzzy sur les equipes
    by_day: dict[tuple[str, str], list[str]] = defaultdict(list)
    for mid, rep in representatives.items():
        by_day[(rep.sport, _day_key(rep))].append(mid)

    canonical: dict[str, str] = {}  # match_id -> match_id canonique du cluster
    for mids in by_day.values():
        clusters: list[tuple[str, Odd]] = []  # (canonical_mid, representative odd)
        for mid in mids:
            rep = representatives[mid]
            found = None
            for canon_mid, canon_rep in clusters:
                if teams_similar(rep.home_team, canon_rep.home_team, threshold) and \
                   teams_similar(rep.away_team, canon_rep.away_team, threshold):
                    found = canon_mid
                    break
            if found is None:
                clusters.append((mid, rep))
                canonical[mid] = mid
            else:
                canonical[mid] = found

    # 3) reecrire match_id sur les cotes dont le cluster a fusionne
    reconciled: list[Odd] = []
    for odd in pool:
        canon = canonical.get(odd.match_id, odd.match_id)
        reconciled.append(odd if canon == odd.match_id else replace(odd, match_id=canon))
    return reconciled


def reconciliation_report(pool: list[Odd], threshold: int = DEFAULT_THRESHOLD) -> dict:
    """Statistiques de fusion : combien de match_id fusionnes, quels books relies."""
    before = len({o.match_id for o in pool})
    reconciled = reconcile_pool(pool, threshold)
    after = len({o.match_id for o in reconciled})

    cross_book = 0
    by_match: dict[str, set[str]] = defaultdict(set)
    for o in reconciled:
        by_match[o.match_id].add(o.bookmaker)
    cross_book = sum(1 for books in by_match.values() if len(books) >= 2)

    return {
        "match_ids_before": before,
        "match_ids_after": after,
        "merged": before - after,
        "cross_book_matches": cross_book,
    }
