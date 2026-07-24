"""Section FunBet de Paryaj Lakay : paris boostes multi-conditions.

Ces "manual odds boosts" combinent plusieurs conditions a une cote gonflee
(15, 45, 130...). On les parse en conditions elementaires, on les price a
partir des cotes 1xBet, et on estime l'ecart (edge) entre la cote boostee et
le prix "juste" -- c'est la que naissent les surebets a fort pourcentage que
l'utilisateur combine manuellement avec 1xBet.
"""
from .parser import Condition, FunBet, parse_funbet
from .pricing import FunBetValuation, value_funbet

__all__ = ["Condition", "FunBet", "parse_funbet", "FunBetValuation", "value_funbet"]
