"""Client BetConstruct "Swarm" (WebSocket) - decouvert en test live juillet 2026.

Golcash Haiti tourne sur la plateforme white-label **BetConstruct**. Sa config
publique (`/conf.json`) expose :

    socketUrl : wss://eu-swarm-newm.betconstruct.com/
    site_id   : 1345

C'est de loin le meilleur canal de collecte identifie sur les 4 bookmakers :
API structuree, **sans Cloudflare, sans navigateur et sans compte**, avec
l'integralite des marches. Protocole :

1. `request_session` -> ouvre une session (retourne un `sid`)
2. `get` avec un selecteur `what` (champs souhaites) et `where` (filtres)

Les reponses peuvent depasser plusieurs Mo : `max_size` est releve en
consequence.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger("surebet.scrapers.swarm")

DEFAULT_SWARM_URL = "wss://eu-swarm-newm.betconstruct.com/"
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

# Types d'evenements Swarm -> selection canonique (spec MISSION §4)
EVENT_TYPE_TO_SELECTION = {
    "P1": "home",
    "X": "draw",
    "P2": "away",
    "Over": "over",
    "Under": "under",
    "Yes": "over",
    "No": "under",
}

# Types de marches Swarm -> market_type canonique.
# Les marches de NICHE sont prioritaires : mesure live, ils sont nettement
# moins marges que le 1X2, donc c'est la que l'arbitrage est realiste.
MARKET_TYPE_MAP = {
    # --- Marches principaux ---
    "P1XP2": ("1x2", 3),
    "OverUnder": ("goals_total", 2),
    "BothTeamsToScore": ("btts", 2),
    "Team1OverUnder": ("goals_team", 2),
    "Team2OverUnder": ("goals_team", 2),
    # --- Mi-temps (jamais fusionner avec le match entier, spec §6.1) ---
    "HalfTimeResult": ("1x2_1h", 3),
    "HalfTimeOverUnder": ("goals_total_1h", 2),
    "2ndHalfTotalOver/Under": ("goals_total_2h", 2),
    "HalfTimeTeam1OverUnder": ("goals_team_1h", 2),
    "HalfTimeTeam2OverUnder": ("goals_team_1h", 2),
    # --- Corners (noms reels releves sur le flux Golcash) ---
    "CornersOverUnder": ("corners_total", 2),
    "HomeTeamCornersOverUnder": ("corners_team", 2),
    "AwayTeamCornersOverUnder": ("corners_team", 2),
    "TeamWithMostCornersWithDraw": ("corners_1x2", 3),
    "HalfTimeCornersOverUnder": ("corners_total_1h", 2),
    "2ndHalfCornersOver/Under": ("corners_total_2h", 2),
    "HalfTimeTeam1CornersOverUnder": ("corners_team_1h", 2),
    "HalfTimeTeam2CornersOverUnder": ("corners_team_1h", 2),
    "HalfTimeCornersResult": ("corners_1x2_1h", 3),
}

# team_scope par type de marche (evite d'apparier equipe A avec equipe B)
SWARM_TEAM_SCOPE = {
    "Team1OverUnder": "home", "Team2OverUnder": "away",
    "HomeTeamCornersOverUnder": "home", "AwayTeamCornersOverUnder": "away",
    "HalfTimeTeam1OverUnder": "home", "HalfTimeTeam2OverUnder": "away",
    "HalfTimeTeam1CornersOverUnder": "home", "HalfTimeTeam2CornersOverUnder": "away",
}


class SwarmClient:
    """Client WebSocket minimal pour l'API Swarm de BetConstruct."""

    def __init__(self, site_id: int, url: str = DEFAULT_SWARM_URL, language: str = "fra", timeout: float = 60.0):
        self.site_id = site_id
        self.url = url
        self.language = language
        self.timeout = timeout
        self._ws = None
        self.session_id: str | None = None

    async def __aenter__(self) -> "SwarmClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        import websockets

        self._ws = await websockets.connect(
            self.url, ping_interval=None, open_timeout=25, max_size=MAX_MESSAGE_BYTES
        )
        response = await self._send(
            {"command": "request_session",
             "params": {"language": self.language, "site_id": self.site_id, "source": 42}}
        )
        if response.get("code") != 0:
            raise RuntimeError(f"Swarm: ouverture de session refusee: {response}")
        self.session_id = (response.get("data") or {}).get("sid")
        logger.info("Session Swarm ouverte (site_id=%s, sid=%s)", self.site_id, self.session_id)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _send(self, payload: dict[str, Any]) -> dict:
        import asyncio

        payload.setdefault("rid", uuid.uuid4().hex[:12])
        await self._ws.send(json.dumps(payload))
        raw = await asyncio.wait_for(self._ws.recv(), self.timeout)
        return json.loads(raw)

    async def fetch_markets(self, sport_alias: str = "Soccer", game_type: int = 0,
                            market_types: list[str] | None = None) -> dict:
        """Recupere sports/competitions/matchs/marches/evenements.

        `game_type` : 0 = pre-match, 1 = live (spec MISSION §2).
        """
        where: dict[str, Any] = {"sport": {"alias": sport_alias}, "game": {"type": game_type}}
        if market_types:
            where["market"] = {"type": {"@in": market_types}} if len(market_types) > 1 else {"type": market_types[0]}

        response = await self._send({
            "command": "get",
            "params": {
                "source": "betting",
                "what": {
                    "sport": ["id", "name", "alias"],
                    "competition": ["id", "name"],
                    "game": ["id", "team1_name", "team2_name", "start_ts"],
                    "market": ["id", "type", "name"],
                    "event": ["id", "name", "price", "type"],
                },
                "where": where,
            },
        })
        if response.get("code") != 0:
            raise RuntimeError(f"Swarm: requete refusee: {str(response)[:200]}")
        return (response.get("data") or {}).get("data", {})
