"""Tests du moteur d'arbitrage (spec MISSION §5, §7).

test_colombie_ghana() et test_1x2_trois_books() reproduisent les deux
exemples de reference §5.4 et §5.5, calcules a partir des formules
deterministes definies en §5.1-5.3 (implied_margin / roi_percent / split_stakes).
"""
import pytest

from surebet.arbitrage.detector import implied_margin, is_surebet, roi_percent
from surebet.arbitrage.stakes import gains_per_leg, guaranteed_profit, min_guaranteed_gain, split_stakes


class TestImpliedMargin:
    def test_generic_n_outcomes(self):
        assert implied_margin([2.0, 2.0]) == pytest.approx(1.0)
        assert implied_margin([2.0, 2.0, 2.0]) == pytest.approx(1.5)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            implied_margin([])


class TestIsSurebet:
    def test_below_threshold_is_surebet(self):
        assert is_surebet([2.16, 2.00]) is True

    def test_above_threshold_is_not_surebet(self):
        assert is_surebet([1.80, 1.80]) is False

    def test_custom_threshold(self):
        assert is_surebet([1.95, 2.05], threshold=1.02) is True


def test_colombie_ghana():
    """§5.4 — Colombie vs Ghana, "Tirs total Ghana 7.5" (2 issues).

    Paryaj Pam moins 7.5 -> 2.16 ; Golcash plus 7.5 -> 2.00 ; B = 50000 HTG.
    """
    odds = [2.16, 2.00]
    bankroll = 50_000.0

    margin = implied_margin(odds)
    assert margin == pytest.approx(0.96296, abs=1e-5)
    assert is_surebet(odds) is True

    roi = roi_percent(odds)
    assert roi == pytest.approx(3.85, abs=0.01)

    stakes = split_stakes(bankroll, odds, round_to=2)
    assert stakes == [pytest.approx(24038.46, abs=0.01), pytest.approx(25961.54, abs=0.01)]
    assert sum(stakes) == pytest.approx(bankroll, abs=0.01)

    gains = gains_per_leg(stakes, odds)
    assert gains[0] == pytest.approx(gains[1], abs=0.5)
    assert gains[0] == pytest.approx(51923.0, abs=1.0)

    profit = guaranteed_profit(bankroll, odds)
    assert profit == pytest.approx(1923.0, abs=1.0)


def test_1x2_trois_books():
    """§5.5 — Resultat 1X2 agrege sur 3 bookmakers (3 issues).

    Domicile Paryaj Lakay -> 3.55 ; Nul 1xBet -> 3.90 ; Exterieur Golcash -> 3.30.

    NOTE: les valeurs de mises calculees ici via les formules exactes de §5.1-5.3
    (implied_margin/split_stakes en pleine precision) different legerement de
    celles affichees dans le texte de la mission (16745.35 / 15242.34 / 18012.31,
    profit 9445), qui semblent provenir d'un arrondi intermediaire de M dans le
    fichier Excel source (non fourni). Verification par fractions exactes :
    M = 1/3.55+1/3.90+1/3.30 = 8540/10153, et Mise_i = B/(Cote_i*M) donne
    16744.73 / 15242.00 / 18013.27 (somme exacte = 50000.00), profit = 9443.80.
    Ces valeurs sont internement coherentes avec la formule deterministe
    (contrairement a celles du texte, qui ne satisfont pas Mise_i = B/(Cote_i*M)
    pour les memes cotes). A confirmer avec l'utilisateur si le fichier Excel
    original donne une precision differente.
    """
    odds = [3.55, 3.90, 3.30]  # [home, draw, away]
    bankroll = 50_000.0

    margin = implied_margin(odds)
    assert margin == pytest.approx(0.84113, abs=1e-5)
    assert is_surebet(odds) is True

    roi = roi_percent(odds)
    assert roi == pytest.approx(18.8876, abs=0.001)

    stakes = split_stakes(bankroll, odds, round_to=2)
    assert stakes[0] == pytest.approx(16744.73, abs=0.01)
    assert stakes[1] == pytest.approx(15242.00, abs=0.01)
    assert stakes[2] == pytest.approx(18013.27, abs=0.01)
    assert sum(stakes) == pytest.approx(bankroll, abs=0.01)

    gains = gains_per_leg(stakes, odds)
    for g in gains:
        assert g == pytest.approx(gains[0], abs=1.0)

    profit = guaranteed_profit(bankroll, odds)
    assert profit == pytest.approx(9443.8, abs=1.0)


class TestSplitStakesRounding:
    def test_integer_rounding_residual_on_highest_odds(self):
        """§5.6 — arrondi entier avec ajustement residuel sur la cote la plus elevee."""
        odds = [3.55, 3.90, 3.30]
        bankroll = 50_000.0
        stakes = split_stakes(bankroll, odds, round_to=0)
        assert sum(stakes) == pytest.approx(bankroll, abs=0.01)
        for s in stakes:
            assert s == round(s)

    def test_min_guaranteed_gain_alert_condition(self):
        odds = [2.16, 2.00]
        bankroll = 50_000.0
        stakes = split_stakes(bankroll, odds, round_to=0)
        assert min_guaranteed_gain(stakes, odds) > bankroll


class TestNotSurebet:
    def test_margin_above_one_returns_false(self):
        assert is_surebet([1.8, 1.9]) is False
        assert implied_margin([1.8, 1.9]) > 1.0
