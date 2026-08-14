"""Scraper MelBet — meme plateforme que 1xBet, donc meme flux LineFeed.

Verifie le 12 aout 2026 : `https://melbet.com/service-api/LineFeed/Get1x2_VZip`
repond exactement comme celui de 1xBet, avec la meme structure `E[]` de
marches identifies par (G, T). Seul l'identifiant `partner` change — 8 pour
MelBet, 151 pour 1xBet. Avec `partner=1`, l'API repond 406.

Ecrire un second scraper aurait duplique 200 lignes pour changer deux
valeurs : on herite. La carte des marches, les regles d'exclusion (le Double
Chance et ses issues qui se recouvrent) et le calcul restent partages — une
correction profite aux deux bookmakers.

RESERVE COMMERCIALE, a garder en tete. MelBet et 1xBet appartiennent au meme
groupe et partagent leur moteur de cotes : entre ces deux-la, les ecarts sont
rares et un arbitrage detecte doit etre regarde de pres. C'est face a
Golcash, Paryaj Pam et Paryaj Lakay que MelBet apporte quelque chose.
"""
from __future__ import annotations

from .xbet import XBetScraper

MELBET_PARTNER = 8


class MelBetScraper(XBetScraper):
    bookmaker_name = "MelBet"

    def __init__(self, base_url: str = "https://melbet.com",
                 partner: int = MELBET_PARTNER, **kwargs) -> None:
        # ht.melbet.com existe mais presente un certificat invalide : on reste
        # sur le domaine principal, qui repond correctement depuis Haiti.
        super().__init__(base_url=base_url, partner=partner, **kwargs)
