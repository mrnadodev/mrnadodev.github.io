"""Notifier Telegram (spec MISSION §8).

Alerte des qu'une opportunite atteint ROI >= 2% ET score_ia >= 70 : calcul
complet, mises arrondies, liens directs vers les pages de pari, explication IA.
Envoi via l'API Bot Telegram (httpx) ; scaffold uniquement (pas de token en dur).
"""
from __future__ import annotations

import logging

import httpx

from ..normalizer.schema import Opportunity

logger = logging.getLogger("surebet.notifier.telegram")


def should_alert(opp: Opportunity, min_roi: float = 2.0, min_score: int = 70) -> bool:
    """Declenche l'alerte si ROI >= min_roi ET score_ia >= min_score (spec MISSION §8)."""
    if opp.score_ia is None:
        return False
    return opp.roi_pct >= min_roi and opp.score_ia >= min_score


def format_alert(opp: Opportunity) -> str:
    """Message Markdown : calcul complet, mises arrondies, liens directs, explication."""
    header = (
        f"*SUREBET {opp.roi_pct:.2f}%* — {opp.match_label}\n"
        f"_{opp.sport} · {opp.market_type}"
        + (f" · ligne {opp.line}" if opp.line is not None else "")
        + f" · {opp.n_outcomes} issues_\n"
    )
    stats = (
        f"Marge M : `{opp.margin:.4f}`\n"
        f"Bankroll : `{opp.bankroll:.0f}` HTG → Profit garanti : *{opp.profit:.0f} HTG*\n"
        f"Score IA : `{opp.score_ia}/100`\n"
    )
    legs_lines = []
    for i, leg in enumerate(opp.legs, start=1):
        legs_lines.append(
            f"{i}. *{leg.selection}* @ `{leg.odds}` chez *{leg.bookmaker}* → miser `{leg.stake:.0f}` HTG\n"
            f"   [Placer le pari]({leg.url})"
        )
    legs_block = "\n".join(legs_lines)
    explanation = f"\n\n_{opp.explanation}_" if opp.explanation else ""
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
            "parse_mode": "Markdown",
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
