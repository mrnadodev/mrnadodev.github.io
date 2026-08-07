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


__all__ = ["find_funbet_arbitrage", "MAX_CONDITIONS"]
