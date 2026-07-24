"""Client WebSocket Paryaj Pam - protocole reconstitue en test live (juillet 2026).

Decouverte : le feed de cotes n'est pas l'API REST `admin-prod.newfeed...`
(qui exige un compte), mais un WebSocket dedie qui accepte le **token public
`demo`** — donc **sans compte, sans navigateur et sans Cloudflare**.

Protocole (capture via un hook `add_init_script` pose avant le JS de la page) :

    wss://wss-new.sport.paryajpam.com/ws/?token=demo&ln=en

    1. {"lang":"en","action":"auth","token":"demo","tree":false,"hot":false}
       -> {"action":"auth","result":true}
    2. {"lang":"en","action":"mnames"}
       -> dictionnaire des types de marches (1=Winner2Ways, 2=Winner3Ways,
          4=Total, 5=Team1Total, 6=Team2Total, ...)
    3. {"lang":"en","action":"hot2","sport":-1,"count":N,"mcount":M,"marker":"all"}
       -> evenements, chacun portant ses marches dans `mr` :
          mr[hash] = {"tp": <type>, "nm": "Winner3Ways",
                      "ou": [ {"<cle>": {"nm":"Win1","kf":1.73,"vl":""}} , ... ]}
          `kf` = la cote, `vl` = la ligne (2.5, 7.5...) pour les marches a seuil.
"""
from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger("surebet.scrapers.pamws")

DEFAULT_WS_URL = "wss://wss-new.sport.paryajpam.com/ws/?token=demo&ln=en"
DEMO_TOKEN = "demo"
ORIGIN = "https://paryajpam.com"
MAX_MESSAGE_BYTES = 64 * 1024 * 1024

# `tp` du marche -> (market_type canonique, n_outcomes)
MARKET_TYPE_BY_TP = {
    1: ("winner_2way", 2),
    2: ("1x2", 3),
    4: ("goals_total", 2),
    5: ("goals_team", 2),
    6: ("goals_team", 2),
}

# Nom d'issue -> selection canonique (spec MISSION §4)
OUTCOME_TO_SELECTION = {
    "Win1": "home",
    "Draw": "draw",
    "Win2": "away",
    "Over": "over",
    "Under": "under",
    "Yes": "over",
    "No": "under",
}

# `tp` du marche -> team_scope (marches par equipe)
TEAM_SCOPE_BY_TP = {5: "home", 6: "away"}

# `pn` (nom de periode) -> suffixe de market_type.
# CRITIQUE : le flux renvoie le meme `tp` pour le temps reglementaire et pour
# chaque mi-temps ("MainTime", "Half1", "Half2"). Sans ce suffixe, un 1X2 de
# 1ere mi-temps serait apparie avec un 1X2 de match entier -> faux arbitrage
# (meme regle que markets.py, spec MISSION §6.1).
PERIOD_SUFFIX = {
    "MainTime": "",
    "Half1": "_1h",
    "Half2": "_2h",
}


def period_suffix(market: dict) -> str | None:
    """Suffixe de periode ; None si la periode est inconnue (marche a ecarter)."""
    return PERIOD_SUFFIX.get(market.get("pn"))


class ParyajPamWSClient:
    """Client minimal du WebSocket de cotes Paryaj Pam (token demo)."""

    def __init__(self, url: str = DEFAULT_WS_URL, token: str = DEMO_TOKEN,
                 language: str = "en", timeout: float = 30.0) -> None:
        self.url = url
        self.token = token
        self.language = language
        self.timeout = timeout
        self._ws = None

    async def __aenter__(self) -> "ParyajPamWSClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        import websockets

        self._ws = await websockets.connect(
            self.url, ping_interval=None, open_timeout=25,
            max_size=MAX_MESSAGE_BYTES, origin=ORIGIN,
        )
        await self._send({"lang": self.language, "action": "auth", "token": self.token,
                          "tree": False, "hot": False})
        auth = await self._recv_action("auth")
        if not auth or not auth.get("result"):
            raise RuntimeError(f"Paryaj Pam: authentification refusee: {auth}")
        logger.info("Paryaj Pam: session WebSocket ouverte (token=%s)", self.token)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _send(self, payload: dict) -> None:
        await self._ws.send(json.dumps(payload))

    async def _recv_action(self, action: str, tries: int = 15) -> dict | None:
        """Lit jusqu'a trouver la reponse de `action` (le flux pousse aussi des updates)."""
        for _ in range(tries):
            raw = await asyncio.wait_for(self._ws.recv(), self.timeout)
            message = json.loads(raw)
            if message.get("action") == action:
                return message
        return None

    async def fetch_market_names(self) -> dict:
        await self._send({"lang": self.language, "action": "mnames"})
        message = await self._recv_action("mnames")
        return (message or {}).get("data", {})

    async def fetch_events(self, sport: int = -1, count: int = 50, mcount: int = 30) -> dict:
        """Evenements avec leurs marches. `mcount` = nombre de marches par match."""
        await self._send({"lang": self.language, "action": "hot2", "sport": sport,
                          "count": count, "mcount": mcount, "marker": "all"})
        message = await self._recv_action("hot2")
        return (message or {}).get("data", {})


def parse_outcomes(market: dict) -> list[tuple[str, float, float | None]]:
    """Extrait (selection, cote, ligne) des issues d'un marche.

    La structure `ou` est une liste de dicts a une seule cle opaque, dont la
    valeur porte `nm` (nom d'issue), `kf` (la cote) et `vl` (la ligne).
    """
    results: list[tuple[str, float, float | None]] = []
    for entry in market.get("ou") or []:
        if not isinstance(entry, dict):
            continue
        for outcome in entry.values():
            if not isinstance(outcome, dict):
                continue
            selection = OUTCOME_TO_SELECTION.get(outcome.get("nm"))
            coefficient = outcome.get("kf")
            if selection is None or not coefficient:
                continue
            try:
                odds = float(coefficient)
            except (TypeError, ValueError):
                continue
            if odds <= 1.0:
                continue
            results.append((selection, odds, _parse_line(outcome.get("vl"), market.get("vl"))))
    return results


def _parse_line(outcome_value, market_value) -> float | None:
    """Seuil du marche (2.5, 7.5...), porte par l'issue ou par le marche."""
    for candidate in (outcome_value, market_value):
        if candidate in (None, ""):
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None
