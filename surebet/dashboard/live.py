"""Vue live du dashboard : scan en direct + mise en forme des opportunites.

Separe la logique (testable hors-ligne) du rendu web. Fournit :
- des libelles d'issue lisibles (home -> "Victoire Domicile (1)") ;
- le classement des meilleures combinaisons cross-bookmakers, surebets ET
  quasi-surebets, pour que l'utilisateur voie toujours les cotes par issue ;
- un scan live sur les books a API rapide (sans navigateur).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ..arbitrage.combinatorics import best_three_way, best_two_way, group_by_match_market
from ..arbitrage.detector import implied_margin, roi_percent
from ..arbitrage.reconcile import reconcile_pool
from ..arbitrage.stakes import split_stakes
from ..normalizer.schema import Odd


def prematch_only(pool: list[Odd], grace_minutes: float = 0.0) -> list[Odd]:
    """Ne garde que les matchs PAS ENCORE commences (arbitrage pre-match).

    Ecarte tout match dont le coup d'envoi est passe : un match en cours cote
    en "live" chez un book et en "pre-match" chez un autre produirait une
    comparaison faussee. `grace_minutes` : marge avant le coup d'envoi.
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) + timedelta(minutes=grace_minutes)
    return [o for o in pool if o.start_time.astimezone(timezone.utc) > cutoff]

# selection -> (libelle FR, symbole)
OUTCOME_LABELS = {
    "home": ("Victoire Domicile", "1"),
    "draw": ("Nul", "X"),
    "away": ("Victoire Extérieur", "2"),
    "over": ("Plus de", "+"),
    "under": ("Moins de", "-"),
}

# market_type canonique -> libelle marche affiche
MARKET_LABELS = {
    "1x2": "3-Way (1X2)",
    "1x2_1h": "3-Way 1re MT",
    "1x2_2h": "3-Way 2e MT",
    "goals_total": "Total buts",
    "goals_team": "Total buts équipe",
    "btts": "Les deux marquent",
    "corners_total": "Total corners",
    "corners_team": "Corners équipe",
    "corners_1x2": "Corners 3-Way",
    "cards_total": "Total cartons",
    "shots_total": "Total tirs",
    "shots_on_target_total": "Tirs cadrés",
    "fouls_total": "Total fautes",
    "tackles_total": "Total tacles",
    "offside_total": "Total hors-jeu",
    "saves_total": "Arrêts gardien",
}


def outcome_label(selection: str, line: float | None, team_scope: str | None) -> str:
    """Libelle lisible d'une issue : "Victoire Domicile (1)", "Plus de 2.5"."""
    name, symbol = OUTCOME_LABELS.get(selection, (selection, selection))
    if selection in ("over", "under") and line is not None:
        scope = {"home": " dom.", "away": " ext."}.get(team_scope, "")
        return f"{name} {line:g}{scope}"
    return f"{name} ({symbol})"


def market_label(market_type: str, line: float | None = None) -> str:
    base = MARKET_LABELS.get(market_type, market_type)
    if line is not None and "Total" in base:
        return f"{base} {line:g}"
    return base


@dataclass(slots=True)
class LiveLeg:
    bookmaker: str
    selection: str
    outcome: str
    odds: float
    stake: float
    url: str


@dataclass(slots=True)
class LiveOpportunity:
    match: str
    sport: str
    competition: str
    market: str
    market_type: str
    n_issues: int
    margin: float
    roi_pct: float
    profit: float
    bankroll: float
    is_surebet: bool
    legs: list[LiveLeg] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def rank_cross_book(
    pool: list[Odd], bankroll: float = 50_000.0, limit: int = 40
) -> list[LiveOpportunity]:
    """Meilleure combinaison cross-bookmakers par marche, classee par marge.

    Inclut les surebets (M < 1) ET les quasi-surebets, pour que le tableau
    montre toujours les cotes par issue. Seules les combinaisons reunissant au
    moins deux bookmakers distincts sont retenues.
    """
    pool = prematch_only(pool)   # arbitrage pre-match : ecarter les matchs commences
    pool = reconcile_pool(pool)  # relier les memes matchs entre books (fuzzy)
    results: list[LiveOpportunity] = []
    for (_, market_type, line, team_scope), group in group_by_match_market(pool).items():
        if not group:
            continue
        combo = best_two_way(group) if group[0].n_outcomes == 2 else best_three_way(group)
        if combo is None:
            continue
        if len({o.bookmaker for o in combo}) < 2:
            continue

        odds_values = [o.odds for o in combo]
        margin = implied_margin(odds_values)
        is_surebet = margin < 1.0
        stakes = split_stakes(bankroll, odds_values, round_to=0) if is_surebet else [0.0] * len(combo)

        ref = combo[0]
        legs = [
            LiveLeg(
                bookmaker=o.bookmaker,
                selection=o.selection,
                outcome=outcome_label(o.selection, o.line, o.team_scope),
                odds=o.odds,
                stake=stake,
                url=o.url,
            )
            for o, stake in zip(combo, stakes)
        ]
        results.append(
            LiveOpportunity(
                match=f"{ref.home_team} - {ref.away_team}",
                sport=ref.sport,
                competition=ref.competition,
                market=market_label(market_type, line),
                market_type=market_type,
                n_issues=len(combo),
                margin=margin,
                roi_pct=roi_percent(odds_values),
                profit=bankroll * (1.0 / margin - 1.0),
                bankroll=bankroll,
                is_surebet=is_surebet,
                legs=legs,
            )
        )
    results.sort(key=lambda o: o.margin)
    return results[:limit]


def scan_stats(pool: list[Odd], opportunities: list[LiveOpportunity]) -> dict:
    """Statistiques d'entete facon 'Arbitrage Scanner Pro'."""
    matches = {o.match_id for o in pool}
    bookmakers = sorted({o.bookmaker for o in pool})
    return {
        "matches_analysed": len(matches),
        "bookmakers": bookmakers,
        "bookmakers_count": len(bookmakers),
        "surebets": sum(1 for o in opportunities if o.is_surebet),
        "combos": len(opportunities),
    }
