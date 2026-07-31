-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Migration « page d'accueil »                              ║
-- ║  Un agrégat public pour prouver l'activité SANS livrer le produit.    ║
-- ║  À exécuter dans Supabase → SQL Editor → Run.                         ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ─────────────────────────────────────────────────────────────────────────
-- POURQUOI CETTE FONCTION
--
-- La RLS interdit à un visiteur non abonné de lire la table « signals » :
-- c'est exactement ce qu'on veut, les signaux SONT le produit payant.
-- Mais la page d'accueil a besoin de prouver qu'il se passe quelque chose,
-- sinon elle n'est qu'une promesse.
--
-- La fonction ci-dessous s'exécute avec les droits de son propriétaire
-- (security definer) et ne renvoie QUE deux nombres agrégés :
--   · combien de signaux sont actifs en ce moment
--   · le meilleur ROI parmi eux
--
-- Aucun match, aucun bookmaker, aucune cote, aucun identifiant ne sort.
-- Il est impossible de reconstituer un signal à partir de ces deux nombres.
-- ─────────────────────────────────────────────────────────────────────────

create or replace function public.signals_teaser()
returns table (active_count integer, best_roi numeric)
language sql
security definer
set search_path = public
stable
as $$
  select
    count(*)::integer                       as active_count,
    coalesce(max(roi), 0)::numeric          as best_roi
  from public.signals
  where expires_at > now();
$$;

-- Verrouillage des droits d'exécution : on retire le défaut trop large,
-- puis on autorise explicitement le visiteur anonyme et l'utilisateur connecté.
revoke all on function public.signals_teaser() from public;
grant execute on function public.signals_teaser() to anon, authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- Vérification :
--   select * from public.signals_teaser();
--
-- Attendu : une seule ligne, par exemple  active_count = 3 | best_roi = 4.12
-- Si active_count vaut 0, la page d'accueil masque simplement le bandeau
-- plutôt que d'afficher un chiffre creux.
-- ─────────────────────────────────────────────────────────────────────────
