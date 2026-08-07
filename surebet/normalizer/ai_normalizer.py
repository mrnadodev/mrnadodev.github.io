"""Fallback LLM de normalisation semantique (spec MISSION §6.1, §6.4).

Pipeline : regles deterministes d'abord (markets.py) ; appel LLM uniquement
si aucune regle ne matche ou si confidence < seuil. Sorties LLM validees en
JSON strict par Pydantic ; en cas d'echec de parsing, rejet et repli sur les
regles (jamais de crash, jamais d'appel LLM dans le chemin critique du calcul
d'arbitrage - §6.4).
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from .markets import MarketMatch, normalize_market_label

logger = logging.getLogger("surebet.ai_normalizer")

PROMPT_PATH = Path(__file__).parent / "prompts" / "market_normalization.txt"
VALID_SELECTIONS = {"over", "under", "home", "draw", "away"}


class LLMMappingOutput(BaseModel):
    """Schema JSON strict attendu du LLM (spec MISSION §6.1)."""

    market_type: str = Field(min_length=1, max_length=64)
    selection: str
    line: float | None = None
    team_scope: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    def to_market_match(self) -> MarketMatch:
        n_outcomes = 3 if self.selection in ("home", "draw", "away") else 2
        return MarketMatch(
            market_type=self.market_type,
            selection=self.selection,
            n_outcomes=n_outcomes,
            line=self.line,
            team_scope=self.team_scope,
            confidence=self.confidence,
        )


class NormalizationCache(Protocol):
    def get(self, key: str) -> MarketMatch | None: ...
    def set(self, key: str, value: MarketMatch) -> None: ...


class InMemoryNormalizationCache:
    """Cache libelle -> mapping par defaut (spec MISSION §6.1).

    Interface minimale (get/set) volontairement compatible avec un cache
    persistant (ex: table SQLite via storage/repository.py) branche par main.py.
    """

    def __init__(self) -> None:
        self._store: dict[str, MarketMatch] = {}

    def get(self, key: str) -> MarketMatch | None:
        return self._store.get(key)

    def set(self, key: str, value: MarketMatch) -> None:
        self._store[key] = value


def cache_key(market_label: str, selection_label: str, home_team: str, away_team: str,
              sport: str = "football") -> str:
    """Cle de cache d'une normalisation.

    Le sport en fait partie : « Resultat du match » vaut TROIS issues au
    football et DEUX au basket. Sans lui, une entree mise en cache pour
    l'un servirait a l'autre — et le cas n'est pas theorique, le Real
    Madrid et Barcelone ont une equipe dans les deux disciplines.

    Ce changement invalide les entrees existantes : elles seront
    recalculees une fois, puis remises en cache.
    """
    return "|".join(
        s.strip().lower()
        for s in (sport, market_label, selection_label, home_team, away_team)
    )


class LLMCallBudgetExceeded(Exception):
    pass


class HourlyBudget:
    """Budget d'appels LLM plafonne par heure, journalise (spec MISSION §6.4)."""

    def __init__(self, max_calls_per_hour: int) -> None:
        self.max_calls_per_hour = max_calls_per_hour
        self._calls: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._calls and now - self._calls[0] > 3600:
            self._calls.popleft()

    def try_consume(self) -> bool:
        now = time.monotonic()
        self._prune(now)
        if len(self._calls) >= self.max_calls_per_hour:
            logger.warning(
                "Budget LLM horaire depasse (%s/%s appels)", len(self._calls), self.max_calls_per_hour
            )
            return False
        self._calls.append(now)
        return True

    @property
    def calls_last_hour(self) -> int:
        self._prune(time.monotonic())
        return len(self._calls)


class LLMClient(Protocol):
    async def complete_json(self, prompt: str) -> str: ...


class AnthropicLLMClient:
    """Client Anthropic reel (spec MISSION §6.4 : provider configurable via .env)."""

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic  # import tardif : evite une dependance dure au module si non utilise

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete_json(self, prompt: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if hasattr(block, "text"))


class AiNormalizer:
    def __init__(
        self,
        llm_client: LLMClient | None,
        cache: NormalizationCache | None = None,
        budget: HourlyBudget | None = None,
        confidence_threshold: float = 0.9,
    ) -> None:
        self.llm_client = llm_client
        self.cache = cache or InMemoryNormalizationCache()
        self.budget = budget or HourlyBudget(max_calls_per_hour=200)
        self.confidence_threshold = confidence_threshold
        self._prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    async def normalize(
        self,
        market_label: str,
        selection_label: str,
        home_team: str,
        away_team: str,
        sport: str = "football",
    ) -> MarketMatch | None:
        rule_result = normalize_market_label(market_label, selection_label, home_team, away_team, sport)
        if rule_result is not None and rule_result.confidence >= self.confidence_threshold:
            return rule_result

        key = cache_key(market_label, selection_label, home_team, away_team, sport)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        if self.llm_client is None:
            logger.info("Pas de client LLM configure, repli sur la regle (ou None): %s", market_label)
            return rule_result

        if not self.budget.try_consume():
            return rule_result

        llm_result = await self._call_llm(market_label, selection_label, home_team, away_team, sport)
        if llm_result is None:
            return rule_result

        best = _pick_best(rule_result, llm_result)
        self.cache.set(key, best)
        return best

    async def _call_llm(
        self, market_label: str, selection_label: str, home_team: str, away_team: str, sport: str
    ) -> MarketMatch | None:
        prompt = self._prompt_template.format(
            sport=sport,
            home_team=home_team,
            away_team=away_team,
            market_label=market_label,
            selection_label=selection_label,
        )
        try:
            raw = await self.llm_client.complete_json(prompt)
        except Exception:
            logger.exception("Echec de l'appel LLM pour %r / %r", market_label, selection_label)
            return None

        try:
            payload = json.loads(_extract_json(raw))
            parsed = LLMMappingOutput.model_validate(payload)
        except (json.JSONDecodeError, ValidationError):
            logger.warning("Sortie LLM invalide, rejetee: %r", raw)
            return None

        if parsed.selection not in VALID_SELECTIONS:
            logger.warning("Selection LLM hors vocabulaire, rejetee: %r", parsed.selection)
            return None

        return parsed.to_market_match()


def _extract_json(text: str) -> str:
    """Extrait le premier objet JSON d'une reponse LLM (au cas ou du texte l'entoure)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def _pick_best(rule_result: MarketMatch | None, llm_result: MarketMatch) -> MarketMatch:
    if rule_result is None:
        return llm_result
    return llm_result if llm_result.confidence > rule_result.confidence else rule_result
