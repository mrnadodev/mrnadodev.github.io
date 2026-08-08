"""Notifier Telegram (spec MISSION §8).

Alerte des qu'une opportunite atteint ROI >= 2% ET score_ia >= 70 : calcul
complet, mises arrondies, liens directs vers les pages de pari, explication IA.
Envoi via l'API Bot Telegram (httpx) ; scaffold uniquement (pas de token en dur).
"""
from __future__ import annotations

import html
import logging

import httpx

from ..normalizer.schema import Opportunity


def _esc(value) -> str:
    """Echappe pour le parse_mode HTML de Telegram (seuls & < > importent)."""
    return html.escape(str(value), quote=False)

logger = logging.getLogger("surebet.notifier.telegram")


def should_alert(
    opp: Opportunity,
    min_roi: float = 2.0,
    min_score: int = 70,
    only_bookmaker: str | None = None,
) -> bool:
    """Declenche l'alerte si ROI >= min_roi ET score_ia >= min_score (spec MISSION §8).

    `only_bookmaker` restreint les alertes aux occasions dont au moins une jambe
    vient de ce bookmaker. Ce n'est pas un confort : depuis aout 2026, l'API de
    Paryaj Lakay refuse l'adresse du VPS (403), alors qu'elle repond depuis une
    connexion haitienne. Deux machines se partagent donc le marche — le VPS
    couvre les trois autres bookmakers, une machine en Haiti couvre Lakay.

    Sans ce filtre, la seconde machine reenverrait toutes les occasions que le
    VPS a deja signalees, et l'abonne recevrait chaque surebet en double. Avec
    lui, le recouvrement est nul par construction : le VPS ne peut pas voir une
    occasion qui contient Lakay, puisqu'il n'obtient aucune de ses cotes.

    La comparaison ignore la casse et les espaces de bordure : la valeur vient
    d'une variable d'environnement, saisie a la main.
    """
    if opp.score_ia is None:
        return False
    if opp.roi_pct < min_roi or opp.score_ia < min_score:
        return False
    if only_bookmaker:
        vise = only_bookmaker.strip().casefold()
        if not any((leg.bookmaker or "").strip().casefold() == vise for leg in opp.legs):
            return False
    return True


def format_alert(opp: Opportunity) -> str:
    """Message HTML : calcul complet, mises arrondies, liens directs, explication.

    HTML plutot que Markdown : les noms d'equipes et market_type contiennent des
    caracteres (`_`, `*`...) qui cassent le parseur Markdown herite de Telegram.
    En HTML, seuls &, <, > doivent etre echappes (via _esc).
    """
    ligne = f" · ligne {_esc(opp.line)}" if opp.line is not None else ""
    header = (
        f"<b>SUREBET {opp.roi_pct:.2f}%</b> — {_esc(opp.match_label)}\n"
        f"<i>{_esc(opp.sport)} · {_esc(opp.market_type)}{ligne} · {opp.n_outcomes} issues</i>\n"
    )
    score = f"{opp.score_ia}/100" if opp.score_ia is not None else "—"
    stats = (
        f"Marge M : <code>{opp.margin:.4f}</code>\n"
        f"Bankroll : <code>{opp.bankroll:.0f}</code> HTG → Profit garanti : "
        f"<b>{opp.profit:.0f} HTG</b>\n"
        f"Score IA : <code>{score}</code>\n"
    )
    legs_lines = []
    for i, leg in enumerate(opp.legs, start=1):
        legs_lines.append(
            f"{i}. <b>{_esc(leg.selection)}</b> @ <code>{_esc(leg.odds)}</code> "
            f"chez <b>{_esc(leg.bookmaker)}</b> → miser <code>{leg.stake:.0f}</code> HTG\n"
            f'   <a href="{_esc(leg.url)}">Placer le pari</a>'
        )
    legs_block = "\n".join(legs_lines)
    explanation = f"\n\n<i>{_esc(opp.explanation)}</i>" if opp.explanation else ""
    return f"{header}\n{stats}\n{legs_block}{explanation}"


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, opp: Opportunity) -> bool:
        """Envoie l'alerte. Retourne False (sans lever) si non configure."""
        if not self.is_configured:
            logger.warning(
                "Telegram non configure (token/chat_id manquants) ; alerte non envoyee pour %s",
                opp.match_label,
            )
            return False

        text = format_alert(opp)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception("Echec d'envoi Telegram pour %s", opp.match_label)
            return False
