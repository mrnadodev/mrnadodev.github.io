"""Couvrir un Funbet de Paryaj Lakay par ses conditions inverses.

L'IDEE
    Paryaj Lakay propose des Funbets : plusieurs conditions combinees en ET,
    a une cote promotionnelle. Exemple : « PSG +10 tirs ET +10 fautes @ 3.2 ».
    Le pari ne gagne que si TOUTES les conditions se realisent.

    On peut chercher chez les autres bookmakers les conditions INVERSES —
    « PSG moins de 10 tirs », « PSG moins de 10 fautes » — et couvrir.

LA MATHEMATIQUE, ET POURQUOI ELLE TIENT
    Avec deux conditions A et B, quatre cas sont possibles :

        A et B        -> le Funbet gagne, les couvertures perdent
        A et non-B    -> non-B gagne
        non-A et B    -> non-A gagne
        non-A, non-B  -> les DEUX couvertures gagnent

    Ce n'est donc PAS une partition : le dernier cas paie deux fois. Mais
    comme il paie plus que les autres, il ne peut pas etre le minimum. Le
    retour garanti reste min(f·F, a·α, b·β), et en egalisant ces trois
    termes on retombe exactement sur la condition d'arbitrage habituelle :

        S = 1/F + 1/α + 1/β < 1

    La formule standard s'applique donc telle quelle, et elle est même
    PRUDENTE : le quatrieme cas rapporte davantage que le minimum garanti.

QUAND CA MARCHE — ET QUAND CA NE PEUT PAS
    A prix justes et conditions independantes, on montre que

        S = 1 + P(non-A et non-B)

    donc S > 1 TOUJOURS. La couverture double du quatrieme cas est un cout
    structurel : on paie deux fois pour un cas unique.

    Il n'y a arbitrage que si le Funbet est majore de plus que cette
    probabilite. Concretement, cela demande des conditions PROBABLES : si
    A et B sont quasi certaines, P(non-A et non-B) est minuscule, les
    couvertures se prennent a grosse cote et coutent peu.

    A l'inverse, un Funbet a cote 50 correspond a des conditions tres
    improbables : P(non-A et non-B) approche 1, et aucune majoration
    promotionnelle ne peut compenser. Ces Funbets-la sont hors d'atteinte,
    quelle que soit la cote affichee.

    Autrement dit : chercher les Funbets a cote MODESTE sur des conditions
    faciles, pas les gros lots.

CE QUE CE MODULE REFUSE DE FAIRE
    · Couvrir avec le bookmaker qui offre le Funbet. Si la promotion est
      annulee, les deux cotes tombent ensemble et la couverture ne couvre
      plus rien.
    · Traiter une condition « victoire » : son inverse demande DEUX paris
      (nul et exterieur), ce qui casse le modele a une couverture par
      condition.
    · Apparier des lignes differentes. « Plus de 10 tirs » ne se couvre que
      par « moins de 10 tirs », jamais par « moins de 8 ».
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..normalizer.schema import Leg, Odd, Opportunity, make_match_id
from .parser import Condition, FunBet
from .pricing import STAT_TO_MARKET, _which_side

# Un Funbet ne se couvre pas au-dela de quelques conditions : chaque jambe
# supplementaire ajoute un cas de couverture multiple, donc du capital
# immobilise pour rien.
MAX_CONDITIONS = 3


def _mots_significatifs(nom: str | None) -> set[str]:
    """Mots d'un nom d'equipe utilisables pour la reconnaitre dans un texte.

    On ecarte les mots trop courts et les prefixes de club, qui
    apparaissent partout et ne designent personne.
    """
    if not nom:
        return set()
    bruit = {"fc", "ac", "sc", "asc", "cf", "club", "de", "la", "le", "les",
             "du", "des", "united", "city", "real", "sporting", "athletic"}
    return {m for m in nom.lower().replace("-", " ").split()
            if len(m) > 3 and m not in bruit}


def _condition_nomme_une_equipe(cond: Condition, funbet: FunBet) -> bool:
    """Le libelle designe-t-il UNE equipe alors que le parseur n'en a attache aucune ?

    Cas reel releve sur Paryaj Lakay : « Otelul reussit 8 tirs cadres ou + »
    ressort avec team=None, donc comme un total de match. Couvrir cela par
    « moins de 8 tirs dans le match » porterait sur un AUTRE evenement — une
    fausse couverture, precisement ce qu'il faut eviter.

    En cas de doute, on refuse.
    """
    texte = (cond.raw or "").lower()
    for nom in (funbet.home_team, funbet.away_team):
        if any(mot in texte for mot in _mots_significatifs(nom)):
            return True
    return False


def _complement(cond: Condition, pool: list[Odd], exclu: str) -> Odd | None:
    """Cote inverse d'une condition, chez un bookmaker autre que `exclu`.

    Retourne None des que le moindre doute existe : mieux vaut ne rien
    proposer qu'une couverture qui n'en est pas une.
    """
    autres = [o for o in pool if o.bookmaker != exclu]
    if not autres:
        return None

    if cond.kind == "btts":
        # Inverse de « les deux marquent » : « les deux ne marquent pas ».
        candidats = [o for o in autres
                     if o.market_type == "btts" and o.selection == "under"]
        return max(candidats, key=lambda o: o.odds, default=None)

    if cond.kind != "threshold" or cond.stat is None or cond.line is None:
        return None

    # « chaque equipe » : l'inverse est « au moins une des deux echoue »,
    # ce qui n'est pas un pari unique. On refuse.
    if cond.each_team:
        return None

    marche = STAT_TO_MARKET.get((cond.stat, cond.team is not None))
    if marche is None:
        return None

    scope = _which_side(cond, autres) if cond.team else None
    if cond.team and scope is None:
        return None

    candidats = [
        o for o in autres
        if o.market_type == marche
        and o.selection == "under"
        and o.line == cond.line          # meme ligne, sans tolerance
        and o.team_scope == scope
    ]
    # A cotes equivalentes on prend la meilleure : elle reduit la mise de
    # couverture, donc augmente le profit garanti.
    return max(candidats, key=lambda o: o.odds, default=None)


def find_funbet_arbitrage(
    funbet: FunBet,
    pool: list[Odd],
    bankroll: float = 0.0,
    min_roi: float = 1.0,
    funbet_url: str | None = None,
) -> Opportunity | None:
    """Cherche une couverture complete d'un Funbet. None si impossible.

    `pool` doit contenir les cotes du MEME match chez les autres
    bookmakers. Le bookmaker du Funbet est exclu des couvertures.
    """
    if not funbet.is_parsable or not funbet.conditions:
        return None
    if not (funbet.boosted_odds and funbet.boosted_odds > 1):
        return None
    if len(funbet.conditions) > MAX_CONDITIONS:
        return None
    if not pool:
        return None

    offreur = "Paryaj Lakay"
    couvertures: list[Odd] = []
    for cond in funbet.conditions:
        # Le parseur laisse parfois team=None sur une condition qui nomme
        # pourtant une equipe : la couvrir par un total de match porterait
        # sur un autre evenement.
        if cond.team is None and _condition_nomme_une_equipe(cond, funbet):
            return None
        c = _complement(cond, pool, exclu=offreur)
        if c is None:
            return None                  # une seule jambe manquante annule tout
        couvertures.append(c)

    # Deux couvertures identiques signeraient un appariement errone.
    reperes = {(c.bookmaker, c.market_type, c.selection, c.line, c.team_scope)
               for c in couvertures}
    if len(reperes) != len(couvertures):
        return None

    cotes = [funbet.boosted_odds] + [c.odds for c in couvertures]
    marge = sum(1.0 / o for o in cotes)
    if marge >= 1.0:
        return None
    roi = (1.0 / marge - 1.0) * 100.0
    if roi < min_roi:
        return None

    ref = couvertures[0]
    legs = [Leg(
        bookmaker=offreur,
        selection="funbet",
        odds=funbet.boosted_odds,
        url=funbet_url or funbet.event_url or "",
        event_label=f"Funbet : {funbet.description}",
    )]
    for cond, c in zip(funbet.conditions, couvertures):
        legs.append(Leg(
            bookmaker=c.bookmaker,
            selection=c.selection,
            odds=c.odds,
            url=c.url,
            event_label=f"inverse de « {cond.raw.strip()} » : "
                        f"{c.market_type} {c.selection}"
                        + (f" {c.line}" if c.line is not None else ""),
        ))

    # Mises egalisant les trois retours : identique a un arbitrage classique.
    for leg in legs:
        leg.stake = bankroll * (1.0 / leg.odds) / marge if bankroll else 0.0

    return Opportunity(
        match_id=ref.match_id,
        sport=ref.sport,
        match_label=funbet.match or f"{ref.home_team} - {ref.away_team}",
        match_date=ref.start_time,
        market_type="funbet_couvert",
        line=None,
        team_scope=None,
        n_outcomes=len(legs),
        legs=legs,
        margin=marge,
        roi_pct=roi,
        bankroll=bankroll,
        profit=bankroll * (1.0 / marge - 1.0) if bankroll else 0.0,
        detected_at=datetime.now(timezone.utc),
    )


def diagnostiquer_funbet(funbet: FunBet, pool: list[Odd]) -> str:
    """Explique en une phrase pourquoi un Funbet n'est pas couvrable.

    Un refus silencieux n'apprend rien. Sur les deux Funbets reels captures
    chez Paryaj Lakay — cotes 45 et 20 — aucun n'etait couvrable, et sans
    ce diagnostic on ne saurait pas si c'est structurel ou conjoncturel.

    La marge chiffree dit a quelle distance on se trouve : si elle tourne
    toujours autour de 1.7, la couverture des Funbets n'arrivera jamais et
    la fonctionnalite ne merite pas d'etre gardee. Si elle approche 1.05,
    cela vaut la peine de continuer a regarder.
    """
    if not funbet.is_parsable:
        return "libelle non analysable"
    if not funbet.conditions:
        return "aucune condition reconnue"
    if not (funbet.boosted_odds and funbet.boosted_odds > 1):
        return "cote absente ou invalide"
    if len(funbet.conditions) > MAX_CONDITIONS:
        return f"{len(funbet.conditions)} conditions : trop pour une couverture utile"

    manquantes: list[str] = []
    couvertures: list[Odd] = []
    for cond in funbet.conditions:
        if cond.kind == "win":
            manquantes.append("une condition de victoire (son inverse demande 2 paris)")
            continue
        if cond.each_team:
            manquantes.append("un « chaque equipe » (inverse non unitaire)")
            continue
        if cond.team is None and _condition_nomme_une_equipe(cond, funbet):
            manquantes.append(f"« {cond.raw.strip()[:34]} » nomme une equipe "
                              "mais est lue comme un total de match")
            continue
        c = _complement(cond, pool, exclu="Paryaj Lakay")
        if c is None:
            manquantes.append(f"pas de cote inverse pour « {cond.raw.strip()[:40]} »")
        else:
            couvertures.append(c)

    if manquantes:
        return "; ".join(manquantes[:2])

    marge = 1.0 / funbet.boosted_odds + sum(1.0 / c.odds for c in couvertures)
    if marge < 1.0:
        return f"COUVRABLE : marge {marge:.3f}"
    manque = marge - 1.0
    return (f"marge {marge:.3f} (il manque {manque:.3f}) : "
            f"les couvertures coutent trop cher pour une cote de {funbet.boosted_odds:g}")


__all__ = ["find_funbet_arbitrage", "diagnostiquer_funbet", "MAX_CONDITIONS"]
