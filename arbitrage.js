/* ╔══════════════════════════════════════════════════════════════════════╗
   ║  NADOEDGE · Calcul d'arbitrage — le seul endroit où vivent ces        ║
   ║  formules.                                                            ║
   ║                                                                       ║
   ║  POURQUOI UN FICHIER À PART                                           ║
   ║    Les mêmes formules étaient recopiées à trois endroits de           ║
   ║    index.html : le calculateur de mise, le démonstrateur de la page   ║
   ║    d'accueil, et le contrôle du ROI à la publication. Trois copies    ║
   ║    d'un code où une erreur coûte de l'argent à un utilisateur, et     ║
   ║    aucune n'était testée.                                             ║
   ║                                                                       ║
   ║    Ici, elles sont écrites une fois et couvertes par                  ║
   ║    outils/arbitrage.test.js (node --test, sans dépendance).           ║
   ║                                                                       ║
   ║  RÈGLE : ce fichier ne touche NI au DOM, NI au réseau. Que du calcul. ║
   ╚══════════════════════════════════════════════════════════════════════╝ */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ARB = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Marge implicite : S = Σ (1 / cote). Surebet si S < 1. */
  function margin(odds) {
    if (!Array.isArray(odds) || !odds.length) return Infinity;
    var s = 0;
    for (var i = 0; i < odds.length; i++) {
      var o = Number(odds[i]);
      if (!(o > 0)) return Infinity;      // cote absente ou absurde
      s += 1 / o;
    }
    return s;
  }

  function isSurebet(odds) { return margin(odds) < 1; }

  /** ROI garanti en pourcentage : (1/S − 1) × 100. Négatif hors surebet. */
  function roiPercent(odds) {
    var m = margin(odds);
    if (!isFinite(m) || m <= 0) return 0;
    return (1 / m - 1) * 100;
  }

  /** Mises réparties pour un total donné : chaque issue rapporte pareil. */
  function stakesForTotal(total, odds) {
    var m = margin(odds);
    if (!isFinite(m) || m <= 0) return odds.map(function () { return 0; });
    return odds.map(function (o) { return total * (1 / Number(o)) / m; });
  }

  /**
   * Mises calculées à partir d'UNE mise imposée.
   * On connaît le montant déjà placé sur `fixedIndex` ; les autres mises
   * sont calculées pour que toutes les issues rapportent la même chose.
   */
  function stakesFromFixed(fixedStake, fixedIndex, odds) {
    var i = Math.max(0, Math.min(fixedIndex | 0, odds.length - 1));
    var cible = fixedStake * Number(odds[i]);          // retour visé
    return odds.map(function (o) { return cible / Number(o); });
  }

  /** Arrondi des mises au pas demandé (0 = pas d'arrondi). */
  function roundStakes(stakes, step) {
    if (!(step > 0)) return stakes.slice();
    return stakes.map(function (s) { return Math.round(s / step) * step; });
  }

  /**
   * Résultat réel de mises données — c'est CE calcul qui fait foi, pas le
   * ROI théorique : après arrondi, le profit change, et il peut devenir
   * négatif alors que les cotes formaient bien un surebet.
   */
  function outcome(stakes, odds) {
    var total = 0, retours = [];
    for (var i = 0; i < stakes.length; i++) {
      total += stakes[i];
      retours.push(stakes[i] * Number(odds[i]));
    }
    var garanti = retours.length ? Math.min.apply(null, retours) : 0;
    var profit = garanti - total;
    return {
      total: total,
      returns: retours,
      guaranteedReturn: garanti,
      profit: profit,
      roi: total > 0 ? (profit / total) * 100 : 0
    };
  }

  /** Cote adverse minimale pour qu'une cote connue devienne un surebet. */
  function counterOdd(odd) {
    var o = Number(odd);
    if (!(o > 1)) return null;
    var reste = 1 - 1 / o;
    if (reste <= 0) return null;
    return 1 / reste;
  }

  return {
    margin: margin,
    isSurebet: isSurebet,
    roiPercent: roiPercent,
    stakesForTotal: stakesForTotal,
    stakesFromFixed: stakesFromFixed,
    roundStakes: roundStakes,
    outcome: outcome,
    counterOdd: counterOdd
  };
});
