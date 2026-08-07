-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Date de la dernière publication                           ║
-- ║  Supabase → SQL Editor → Run.                                         ║
-- ╚══════════════════════════════════════════════════════════════════════╝
--
-- POURQUOI
--   Le contrôle de santé veut répondre à : « depuis combien de temps aucun
--   surebet n'a été publié pour les abonnés ? » C'est l'alerte la plus
--   utile de toutes : elle prévient qu'un client qui paie ne reçoit rien.
--
--   La table signals est protégée par la RLS — c'est le paywall, et il
--   fonctionne. Sans cette fonction, le seul moyen de lire cette date
--   serait la clé service_role, qui contourne TOUTE la RLS. Déposer une
--   clé d'accès total sur un VPS Windows exposé à internet, pour connaître
--   une date, est un mauvais échange.
--
-- CE QUE ÇA EXPOSE
--   Deux valeurs : la date du dernier signal publié, et le nombre publié
--   sur les 7 derniers jours. Aucun match, aucun bookmaker, aucune cote.
--   Le produit reste entier derrière la RLS.

create or replace function public.derniere_publication()
returns table (
  publie_le      timestamptz,
  heures_depuis  numeric,
  signaux_7j     bigint
)
language sql
security definer
stable
set search_path = public
as $$
  select
    max(created_at),
    round(extract(epoch from (now() - max(created_at))) / 3600.0, 1),
    count(*) filter (where created_at >= now() - interval '7 days')
  from public.signals;
$$;

revoke all on function public.derniere_publication() from public;
grant execute on function public.derniere_publication() to anon, authenticated;

-- Vérification :
--   select * from public.derniere_publication();
--
-- Une base sans aucun signal renvoie une ligne avec des valeurs nulles :
-- c'est correct, et le contrôle de santé le signale comme un problème —
-- vos abonnés n'ont jamais rien reçu.
