-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Classement des 7 derniers jours                           ║
-- ║  A executer dans Supabase → SQL Editor → Run.                         ║
-- ║                                                                        ║
-- ║  Pourquoi une vue ? Les paris (table bets) sont PRIVES : la RLS        ║
-- ║  empeche un utilisateur de lire ceux des autres. Un classement calcule ║
-- ║  cote navigateur est donc impossible. Cette vue n expose QUE le pseudo ║
-- ║  et le profit agrege — jamais le detail des paris.                     ║
-- ╚══════════════════════════════════════════════════════════════════════╝

create or replace view public.leaderboard_7d
with (security_invoker = off)   -- la vue agrege pour tous, sans exposer le detail
as
select
  p.username,
  round(sum( coalesce( (b.payload->>'profit')::numeric, 0 ) )::numeric, 2) as profit,
  count(*) as bets
from public.bets b
join public.profiles p on p.id = b.user_id
where b.status = 'won'
  and b.created_at >= now() - interval '7 days'
  and p.username is not null
group by p.username
having sum( coalesce( (b.payload->>'profit')::numeric, 0 ) ) > 0
order by profit desc
limit 20;

-- Lecture autorisee a tout utilisateur connecte (le detail reste protege)
revoke all on public.leaderboard_7d from anon;
grant select on public.leaderboard_7d to authenticated;

-- ─────────────────────────────────────────────────────────────────────────
-- Verification :
--   select * from public.leaderboard_7d;
-- Tant que cette vue n existe pas, l app affiche simplement
-- « Classement bientot disponible. » sans erreur.
-- ─────────────────────────────────────────────────────────────────────────
