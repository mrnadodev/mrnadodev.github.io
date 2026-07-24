"""Agent de detection d'opportunites (spec MISSION §6.2).

Tourne en continu sur le pool de cotes normalisees :
- genere et evalue toutes les combinaisons 2 et 3 issues cross-bookmakers ;
- detecte les quasi-surebets (0.99 <= M < 1.02) et suit leur trajectoire ;
- identifie les marches/bookmakers les plus generateurs (priorisation scraping) ;
- produit une explication en langage naturel (FR/creole) via le LLM.

Le calcul de M/ROI/mises reste deterministe (arbitrage/) ; le LLM ne sert
qu'a l'explication, hors chemin critique (spec MISSION §6, §6.4).
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..arbitrage.combinatorics import best_three_way, best_two_way, group_by_match_market
from ..arbitrage.detector import find_three_way, find_two_way, implied_margin, roi_percent
from ..arbitrage.stakes import split_stakes
from ..normalizer.schema import Leg, Odd, Opportunity

logger = logging.getLogger("surebet.ai.scout")

QUASI_SUREBET_LOW = 0.99
QUASI_SUREBET_HIGH = 1.02


@dataclass(slots=True)
class QuasiSurebet:
    opportunity: Opportunity
    margin_history: list[tuple[datetime, float]] = field(default_factory=list)

    @property
    def is_improving(self) -> bool:
        """True si la marge M diminue (se rapproche du surebet) sur l'historique."""
        if len(self.margin_history) < 2:
            return False
        return self.margin_history[-1][1] < self.margin_history[0][1]


class Scout:
    def __init__(self, min_roi: float = 1.0, bankroll: float = 50_000.0, llm_client=None) -> None:
        self.min_roi = min_roi
        self.bankroll = bankroll
        self.llm_client = llm_client
        self._market_hit_counter: Counter[str] = Counter()
        self._bookmaker_hit_counter: Counter[str] = Counter()
        self._quasi_tracker: dict[str, QuasiSurebet] = {}

    def evaluate(self, pool: list[Odd]) -> list[Opportunity]:
        """Genere et evalue toutes les combinaisons 2 et 3 issues cross-bookmakers."""
        opportunities = find_two_way(pool, self.min_roi, self.bankroll) + find_three_way(
            pool, self.min_roi, self.bankroll
        )
        for opp in opportunities:
            self._assign_stakes(opp)
            self._market_hit_counter[opp.market_type] += 1
            for leg in opp.legs:
                self._bookmaker_hit_counter[leg.bookmaker] += 1
        return sorted(opportunities, key=lambda o: o.roi_pct, reverse=True)

    def _assign_stakes(self, opp: Opportunity) -> None:
        odds_values = [leg.odds for leg in opp.legs]
        stakes = split_stakes(opp.bankroll, odds_values, round_to=0)
        for leg, stake in zip(opp.legs, stakes):
            leg.stake = stake

    def detect_quasi_surebets(self, pool: list[Odd]) -> list[QuasiSurebet]:
        """Detecte les quasi-surebets (0.99 <= M < 1.02) et suit leur trajectoire.

        Contrairement a evaluate(), on n'utilise pas find_two/three_way (qui
        rejettent M >= 1.0) : la bande quasi-surebet chevauche 1.0, il faut donc
        evaluer les combinaisons directement.
        """
        now = datetime.now(timezone.utc)
        active: list[QuasiSurebet] = []
        for (_, market_type, line, team_scope), group in group_by_match_market(pool).items():
            if not group:
                continue
            combo = best_two_way(group) if group[0].n_outcomes == 2 else best_three_way(group)
            if combo is None:
                continue
            opp = self._combo_to_opportunity(combo, market_type, line, team_scope)
            if not (QUASI_SUREBET_LOW <= opp.margin < QUASI_SUREBET_HIGH):
                continue
            key = self._opp_key(opp)
            tracked = self._quasi_tracker.get(key)
            if tracked is None:
                tracked = QuasiSurebet(opportunity=opp)
                self._quasi_tracker[key] = tracked
            tracked.opportunity = opp
            tracked.margin_history.append((now, opp.margin))
            tracked.margin_history = tracked.margin_history[-10:]
            active.append(tracked)
        return active

    def _combo_to_opportunity(
        self, combo: tuple[Odd, ...], market_type: str, line, team_scope
    ) -> Opportunity:
        odds_values = [o.odds for o in combo]
        margin = implied_margin(odds_values)
        ref = combo[0]
        return Opportunity(
            match_id=ref.match_id,
            sport=ref.sport,
            match_label=f"{ref.home_team} - {ref.away_team}",
            match_date=ref.start_time,
            market_type=market_type,
            line=line,
            team_scope=team_scope,
            n_outcomes=len(combo),
            legs=[
                Leg(
                    bookmaker=o.bookmaker,
                    selection=o.selection,
                    odds=o.odds,
                    url=o.url,
                    event_label=f"{o.market_type} {o.selection}",
                )
                for o in combo
            ],
            margin=margin,
            roi_pct=roi_percent(odds_values),
            bankroll=self.bankroll,
            profit=self.bankroll * (1.0 / margin - 1.0),
        )

    @staticmethod
    def _opp_key(opp: Opportunity) -> str:
        legs = "+".join(sorted(f"{leg.bookmaker}:{leg.selection}" for leg in opp.legs))
        return f"{opp.match_id}|{opp.market_type}|{opp.line}|{legs}"

    def hot_markets(self, top_n: int = 5) -> list[tuple[str, int]]:
        """Marches historiquement les plus generateurs -> concentrer le scraping."""
        return self._market_hit_counter.most_common(top_n)

    def hot_bookmakers(self, top_n: int = 5) -> list[tuple[str, int]]:
        return self._bookmaker_hit_counter.most_common(top_n)

    def scrape_priority(self) -> dict[str, float]:
        """Poids de priorite de scraping par bookmaker (spec MISSION §6.2)."""
        total = sum(self._bookmaker_hit_counter.values())
        if total == 0:
            return {}
        return {bm: count / total for bm, count in self._bookmaker_hit_counter.items()}

    async def explain(self, opp: Opportunity) -> str:
        """Explication en langage naturel (FR/creole) pour l'alerte Telegram.

        Deterministe si aucun LLM configure (repli sur un gabarit) ; sinon appel
        LLM hors chemin critique.
        """
        deterministic = _template_explanation(opp)
        if self.llm_client is None:
            return deterministic
        try:
            from pathlib import Path

            prompt_path = Path(__file__).parent / "prompts" / "opportunity_explanation.txt"
            legs_block = "\n".join(
                f"  - {leg.selection} @ {leg.odds} chez {leg.bookmaker} : miser {leg.stake:.0f} HTG"
                for leg in opp.legs
            )
            prompt = prompt_path.read_text(encoding="utf-8").format(
                match_label=opp.match_label,
                sport=opp.sport,
                market_type=opp.market_type,
                line_info=f" (ligne {opp.line})" if opp.line is not None else "",
                n_outcomes=opp.n_outcomes,
                margin=opp.margin,
                roi_pct=opp.roi_pct,
                bankroll=opp.bankroll,
                profit=opp.profit,
                legs_block=legs_block,
            )
            text = await self.llm_client.complete_json(prompt)
            return text.strip() or deterministic
        except Exception:
            logger.exception("Echec de l'explication LLM, repli sur le gabarit")
            return deterministic


def _template_explanation(opp: Opportunity) -> str:
    lines = [
        f"Surebet {opp.roi_pct:.1f}% sur {opp.match_label} ({opp.market_type}).",
        f"Profit garanti : {opp.profit:.0f} HTG pour {opp.bankroll:.0f} HTG mises.",
    ]
    for leg in opp.legs:
        lines.append(f"- {leg.selection} @ {leg.odds} chez {leg.bookmaker} : {leg.stake:.0f} HTG")
    lines.append("Fè vit, kòt yo ka chanje!")
    return "\n".join(lines)
