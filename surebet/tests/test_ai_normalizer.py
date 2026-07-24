"""Tests du fallback IA (spec MISSION §6.1, §6.4) avec client LLM mocke.

Aucun appel reseau reel : le client LLM est un double de test qui retourne
des reponses JSON controlees, pour valider le pipeline (regles -> cache ->
budget -> validation Pydantic -> repli sur les regles en cas d'echec).
"""
import json

import pytest

from surebet.normalizer.ai_normalizer import (
    AiNormalizer,
    HourlyBudget,
    InMemoryNormalizationCache,
    cache_key,
)

HOME = "Ghana"
AWAY = "Colombie"


class FakeLLMClient:
    def __init__(self, response: str | None = None, raise_error: bool = False):
        self.response = response
        self.raise_error = raise_error
        self.calls = 0

    async def complete_json(self, prompt: str) -> str:
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("simulated LLM failure")
        return self.response


@pytest.mark.asyncio
async def test_confident_rule_match_never_calls_llm():
    llm = FakeLLMClient(response="{}")
    normalizer = AiNormalizer(llm_client=llm)
    result = await normalizer.normalize("Nombre de buts", "> 2.5", HOME, AWAY)
    assert result is not None
    assert result.market_type == "goals_total"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_ambiguous_label_falls_back_to_llm():
    payload = {
        "market_type": "correct_score_group",
        "selection": "home",
        "line": None,
        "team_scope": None,
        "confidence": 0.95,
    }
    llm = FakeLLMClient(response=json.dumps(payload))
    normalizer = AiNormalizer(llm_client=llm)
    result = await normalizer.normalize("Vainqueur du tournoi bizarre", "Ghana", HOME, AWAY)
    assert llm.calls == 1
    assert result is not None
    assert result.market_type == "correct_score_group"
    assert result.confidence == 0.95


@pytest.mark.asyncio
async def test_llm_response_wrapped_in_extra_text_is_parsed():
    payload = {
        "market_type": "goals_total",
        "selection": "over",
        "line": 2.5,
        "team_scope": None,
        "confidence": 0.92,
    }
    wrapped = f"Voici le resultat:\n{json.dumps(payload)}\nFin."
    llm = FakeLLMClient(response=wrapped)
    normalizer = AiNormalizer(llm_client=llm)
    result = await normalizer.normalize("Libelle obscur de buts", "plus de 2.5 sans doute", HOME, AWAY)
    assert result is not None
    assert result.market_type == "goals_total"


@pytest.mark.asyncio
async def test_invalid_json_falls_back_to_rule_result():
    llm = FakeLLMClient(response="ceci n'est pas du json")
    normalizer = AiNormalizer(llm_client=llm)
    # "Total corners" sans direction/ligne -> regle basse confiance (0.5), LLM invalide -> repli sur regle
    result = await normalizer.normalize("Total corners", "Oui", HOME, AWAY)
    assert result is not None
    assert result.market_type == "corners_total"
    assert result.confidence < 0.9


@pytest.mark.asyncio
async def test_invalid_selection_vocabulary_is_rejected():
    payload = {
        "market_type": "btts",
        "selection": "yes",  # hors vocabulaire {over,under,home,draw,away}
        "line": None,
        "team_scope": None,
        "confidence": 0.9,
    }
    llm = FakeLLMClient(response=json.dumps(payload))
    normalizer = AiNormalizer(llm_client=llm)
    result = await normalizer.normalize("Libelle totalement inconnu", "Yes", HOME, AWAY)
    assert result is None  # aucune regle ne matche + LLM rejete


@pytest.mark.asyncio
async def test_llm_exception_does_not_crash_pipeline():
    llm = FakeLLMClient(raise_error=True)
    normalizer = AiNormalizer(llm_client=llm)
    result = await normalizer.normalize("Libelle inconnu total", "valeur", HOME, AWAY)
    assert result is None


@pytest.mark.asyncio
async def test_cache_avoids_second_llm_call():
    payload = {
        "market_type": "handicap_ambiguous",
        "selection": "home",
        "line": -1.0,
        "team_scope": None,
        "confidence": 0.93,
    }
    llm = FakeLLMClient(response=json.dumps(payload))
    normalizer = AiNormalizer(llm_client=llm)
    label, sel = "Handicap Europeen", "1 (0:1)"
    first = await normalizer.normalize(label, sel, HOME, AWAY)
    second = await normalizer.normalize(label, sel, HOME, AWAY)
    assert first == second
    assert llm.calls == 1  # deuxieme appel sert du cache


@pytest.mark.asyncio
async def test_hourly_budget_blocks_llm_and_falls_back_to_rule():
    payload = {"market_type": "x", "selection": "home", "line": None, "team_scope": None, "confidence": 0.9}
    llm = FakeLLMClient(response=json.dumps(payload))
    normalizer = AiNormalizer(llm_client=llm, budget=HourlyBudget(max_calls_per_hour=0))
    result = await normalizer.normalize("Total corners", "Oui", HOME, AWAY)
    assert llm.calls == 0
    assert result is not None
    assert result.market_type == "corners_total"


def test_cache_key_is_case_insensitive():
    a = cache_key("Nombre De Buts", "> 2.5", "Ghana", "Colombie")
    b = cache_key("nombre de buts", "> 2.5", "ghana", "colombie")
    assert a == b


def test_in_memory_cache_get_set():
    cache = InMemoryNormalizationCache()
    assert cache.get("missing") is None
