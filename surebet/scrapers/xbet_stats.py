"""Marches de niche 1xBet via le feed par-evenement (GetGameZip / sous-jeux).

Le feed compact (Get1x2_VZip) ne contient que 1x2/totaux/BTTS. Les statistiques
(corners, tirs, fautes, tacles, cartons, degagements, arrets, VAR, hors-jeu...)
vivent dans des SOUS-JEUX (`SG`) du feed par-evenement, chacun identifie par un
nom `TG` ("Corners", "Tirs Cadres"...) et son propre id.

Decouverte live (juillet 2026) : a l'interieur d'un sous-jeu de stat, la
convention (G, T) est IDENTIQUE a celle du match principal :
    G=17 T=9/10   -> total match  Over/Under (P = ligne)
    G=15 T=11/12  -> total equipe domicile Over/Under
    G=62 T=13/14  -> total equipe exterieure Over/Under
On reutilise donc la meme logique de parsing pour toutes les stats.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime

from ..normalizer.schema import Odd


def _strip(s: str) -> str:
    n = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower().strip()


# Nom de sous-jeu (TG, sans accents) -> prefixe de market_type canonique.
TG_TO_STAT: dict[str, str] = {
    "corners": "corners",
    "tirs cadres": "shots_on_target",
    "tirs vers le but": "shots",
    "fautes": "fouls",
    "cartons jaunes": "cards",
    "cartons": "cards",
    "tacles": "tackles",
    "degagements de but": "goalkicks",
    "sauvetages": "saves",
    "controles var": "var",
    "hors-jeu": "offside",
    "touches": "throwins",
}

# Stat canonique -> libelle FunBet (pour retrouver le sous-jeu a partir d'une
# condition FunBet : "corners" -> chercher le sous-jeu "Corners").
STAT_TO_TG = {v: k for k, v in TG_TO_STAT.items()
              if k not in ("cartons", "tirs vers le but")}

# (G, T) -> (selection, team_scope) : convention over/under standard 1xBet.
STAT_GT_MAP: dict[tuple[int, int], tuple[str, str | None]] = {
    (17, 9): ("over", None), (17, 10): ("under", None),
    (15, 11): ("over", "home"), (15, 12): ("under", "home"),
    (62, 13): ("over", "away"), (62, 14): ("under", "away"),
}


def stat_from_tg(tg: str) -> str | None:
    """Nom de sous-jeu 1xBet -> stat canonique (None si hors perimetre)."""
    return TG_TO_STAT.get(_strip(tg))


def find_stat_subgames(main_value: dict, wanted: set[str]) -> dict[str, int]:
    """Repere les sous-jeux de stat voulus dans le feed principal.

    Retourne {stat_canonique: id_sous_jeu}. On garde le PREMIER sous-jeu par
    stat : c'est celui qui contient le total match + les totaux par equipe
    (verifie live sur les corners).
    """
    out: dict[str, int] = {}
    for sg in main_value.get("SG") or []:
        stat = stat_from_tg(str(sg.get("TG") or ""))
        if stat and stat in wanted and stat not in out and sg.get("I"):
            out[stat] = sg["I"]
    return out


def parse_stat_subgame(
    value: dict, stat: str, home: str, away: str, match_id: str,
    competition: str, url: str, start_time: datetime, scraped_at: datetime,
) -> list[Odd]:
    """Extrait les cotes Over/Under (total + par equipe) d'un sous-jeu de stat."""
    out: list[Odd] = []
    for entry in value.get("E") or []:
        mapped = STAT_GT_MAP.get((entry.get("G"), entry.get("T")))
        if mapped is None:
            continue
        selection, team_scope = mapped
        coefficient = entry.get("C")
        line = entry.get("P")
        if not coefficient or float(coefficient) <= 1.0 or line is None:
            continue
        market_type = f"{stat}_team" if team_scope else f"{stat}_total"
        try:
            out.append(
                Odd(
                    bookmaker="1xBet", sport="football", competition=competition,
                    match_id=match_id, home_team=home, away_team=away,
                    start_time=start_time, market_type=market_type, n_outcomes=2,
                    selection=selection, line=float(line), team_scope=team_scope,
                    odds=float(coefficient), url=url, scraped_at=scraped_at,
                )
            )
        except ValueError:
            continue
    return out
