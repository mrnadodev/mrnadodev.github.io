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

# --- Reconnaissance DYNAMIQUE des marches-stat BetConstruct par motif ---------
#
# Repond a : "si Golcash AJOUTE cartons/fautes/tirs sur un match (ex. Premier
# League), le systeme les reconnaitra-t-il sans que j'aie code chaque nom ?"
# Oui : au lieu d'une liste blanche figee, on detecte le type par mots-cles.
# BetConstruct nomme ses marches de facon reguliere :
#   "{Prefix}OverUnder", "HomeTeam{Prefix}OverUnder", "AwayTeam{Prefix}OverUnder",
#   "HalfTime{Prefix}OverUnder", "2ndHalf{Prefix}Over/Under", ...
import re as _re

# Mots-cles de statistique -> prefixe canonique (ordre : le plus specifique d'abord)
_SWARM_STAT_KEYWORDS: list[tuple[_re.Pattern, str]] = [
    # Pas de \b : les noms BetConstruct sont en camelCase sans separateur
    # ("2ndHalfCardsOverUnder"), donc les frontieres de mot ne s'appliquent pas.
    (_re.compile(r"shots?ontarget", _re.I), "shots_on_target"),
    (_re.compile(r"corners?", _re.I), "corners"),
    (_re.compile(r"yellowcards?|redcards?|cards?", _re.I), "cards"),
    (_re.compile(r"fouls?", _re.I), "fouls"),
    (_re.compile(r"tackles?", _re.I), "tackles"),
    (_re.compile(r"offsides?", _re.I), "offside"),
    (_re.compile(r"goalkicks?", _re.I), "goalkicks"),
    (_re.compile(r"throwins?", _re.I), "throwins"),
    (_re.compile(r"saves?", _re.I), "saves"),
    (_re.compile(r"var", _re.I), "var"),
    (_re.compile(r"shots?", _re.I), "shots"),
]
_SWARM_HOME_RE = _re.compile(r"hometeam|\bteam1\b|home", _re.I)
_SWARM_AWAY_RE = _re.compile(r"awayteam|\bteam2\b|away", _re.I)
_SWARM_OVERUNDER_RE = _re.compile(r"over\s*/?\s*under|totals?\b", _re.I)
_SWARM_HALF1_RE = _re.compile(r"halftime|1sthalf|firsthalf", _re.I)
_SWARM_HALF2_RE = _re.compile(r"2ndhalf|secondhalf", _re.I)
_SWARM_EXCLUDE_RE = _re.compile(r"handicap|asian|oddeven|odd/even|winner|doublechance|raceto|3ways?", _re.I)


def pattern_market(type_str: str) -> tuple[str, int, str | None] | None:
    """Reconnait un marche-stat Over/Under BetConstruct par motif.

    Retourne (market_type, n_outcomes=2, team_scope) ou None. Ne matche que les
    totaux Over/Under (pas handicap/oddeven/1x2, qui ne sont pas des paires
    over/under exploitables ici).
    """
    if not type_str or _SWARM_EXCLUDE_RE.search(type_str):
        return None
    if not _SWARM_OVERUNDER_RE.search(type_str):
        return None
    stat = next((s for rx, s in _SWARM_STAT_KEYWORDS if rx.search(type_str)), None)
    if stat is None:
        return None
    scope = "home" if _SWARM_HOME_RE.search(type_str) else "away" if _SWARM_AWAY_RE.search(type_str) else None
    suffix = "_1h" if _SWARM_HALF1_RE.search(type_str) else "_2h" if _SWARM_HALF2_RE.search(type_str) else ""
    base = f"{stat}_team" if scope else f"{stat}_total"
    return f"{base}{suffix}", 2, scope


def resolve_swarm_market(type_str: str) -> tuple[str, int, str | None] | None:
    """Type BetConstruct -> (market_type, n_outcomes, team_scope).

    Liste blanche explicite d'abord (controle precis), puis reconnaissance par
    motif (capte les marches AJOUTES par l'operateur sans modification du code).
    """
    mapped = MARKET_TYPE_MAP.get(type_str)
    if mapped is not None:
        return mapped[0], mapped[1], SWARM_TEAM_SCOPE.get(type_str)
    return pattern_market(type_str)


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
