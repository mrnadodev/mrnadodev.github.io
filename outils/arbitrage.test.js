/* Tests du calcul d'arbitrage.
 *
 *   node --test outils/
 *
 * Aucune dependance : le module natif node:test suffit. C'est le code ou
 * une erreur coute de l'argent a un utilisateur — il doit etre couvert.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const ARB = require('../arbitrage.js');

const proche = (a, b, tol = 1e-9) =>
  assert.ok(Math.abs(a - b) < tol, `attendu ${b}, obtenu ${a}`);

test('marge : somme des inverses', () => {
  proche(ARB.margin([2, 2]), 1);
  proche(ARB.margin([2, 2, 2]), 1.5);
  proche(ARB.margin([2.10, 2.05]), 1 / 2.10 + 1 / 2.05);
});

test('marge : cote absente ou absurde rend le calcul impossible', () => {
  assert.equal(ARB.margin([]), Infinity);
  assert.equal(ARB.margin([2, 0]), Infinity);
  assert.equal(ARB.margin([2, -1]), Infinity);
  assert.equal(ARB.margin([2, null]), Infinity);
});

test('surebet : S < 1 seulement', () => {
  assert.equal(ARB.isSurebet([2.10, 2.05]), true);   // S = 0.9640
  assert.equal(ARB.isSurebet([2.00, 2.00]), false);  // S = 1 pile : pas de profit
  assert.equal(ARB.isSurebet([2.10, 1.80]), false);
});

test('ROI : exemple de reference 2.10 / 2.05', () => {
  // S = 0.963995 -> ROI = 1/S - 1 = 3.735 %
  proche(ARB.roiPercent([2.10, 2.05]), 3.7349, 1e-3);
});

test('ROI : negatif quand ce n est pas un surebet', () => {
  assert.ok(ARB.roiPercent([2.10, 1.80]) < 0);
});

test('ROI : coherent avec le trigger serveur (formule (1-S)/S)', () => {
  const cotes = [3.55, 3.90, 3.30];
  const S = ARB.margin(cotes);
  proche(ARB.roiPercent(cotes), ((1 - S) / S) * 100);
});

test('mises pour un total : somme au total, retours egaux', () => {
  const cotes = [2.10, 2.05];
  const mises = ARB.stakesForTotal(1000, cotes);
  proche(mises.reduce((a, b) => a + b, 0), 1000, 1e-6);
  proche(mises[0] * cotes[0], mises[1] * cotes[1], 1e-6);
  // Valeurs affichees par le demonstrateur de la page d'accueil.
  assert.equal(Math.round(mises[0]), 494);
  assert.equal(Math.round(mises[1]), 506);
});

test('mises depuis une mise imposee : tous les retours egaux', () => {
  const cotes = [3.55, 3.90, 3.30];
  const mises = ARB.stakesFromFixed(100, 0, cotes);
  proche(mises[0], 100);
  const retours = mises.map((m, i) => m * cotes[i]);
  proche(retours[0], retours[1], 1e-6);
  proche(retours[1], retours[2], 1e-6);
});

test('mise imposee : indice hors bornes ramene dans la plage', () => {
  const cotes = [2.10, 2.05];
  proche(ARB.stakesFromFixed(100, 9, cotes)[1], 100);   // dernier
  proche(ARB.stakesFromFixed(100, -3, cotes)[0], 100);  // premier
});

test('arrondi : pas de 0 laisse les mises intactes', () => {
  const m = [494.4, 505.6];
  assert.deepEqual(ARB.roundStakes(m, 0), m);
});

test('arrondi : au pas de 50', () => {
  assert.deepEqual(ARB.roundStakes([494.4, 505.6], 50), [500, 500]);
});

test('resultat reel : profit et ROI sur les mises effectives', () => {
  const cotes = [2.10, 2.05];
  const mises = ARB.stakesForTotal(1000, cotes);
  const r = ARB.outcome(mises, cotes);
  proche(r.total, 1000, 1e-6);
  proche(r.profit, 1000 / ARB.margin(cotes) - 1000, 1e-6);
  proche(r.roi, ARB.roiPercent(cotes), 1e-6);
});

test('resultat reel : un arrondi trop grossier peut annuler le profit', () => {
  // Le vrai piege : les cotes forment un surebet, mais apres arrondi au
  // millier la repartition est fausse et le gain garanti disparait.
  const cotes = [2.10, 2.05];
  assert.ok(ARB.isSurebet(cotes));
  const arrondies = ARB.roundStakes(ARB.stakesForTotal(1000, cotes), 1000);
  const r = ARB.outcome(arrondies, cotes);
  assert.ok(r.profit < 0, 'le profit doit devenir negatif apres cet arrondi');
});

test('cote adverse : seuil de bascule', () => {
  // Avec 2.10 d un cote, il faut plus de 1.909 de l autre.
  proche(ARB.counterOdd(2.10), 1 / (1 - 1 / 2.10), 1e-9);
  assert.ok(ARB.isSurebet([2.10, ARB.counterOdd(2.10) + 0.01]));
  assert.ok(!ARB.isSurebet([2.10, ARB.counterOdd(2.10) - 0.01]));
});

test('cote adverse : refusee sous 1', () => {
  assert.equal(ARB.counterOdd(1), null);
  assert.equal(ARB.counterOdd(0.5), null);
});
