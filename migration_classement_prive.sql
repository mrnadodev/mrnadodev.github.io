-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Classement sans montants + détection des comptes passifs  ║
-- ║  Supabase → SQL Editor → Run.                                         ║
-- ╚══════════════════════════════════════════════════════════════════════╝


-- ═══════════════════════════════════════════════════════════════════════
-- A · LE CLASSEMENT NE DOIT PLUS CHIFFRER LES GAINS
--
--   La version précédente exposait, à TOUT utilisateur connecté, le pseudo
--   de chaque gagnant, son profit sur 7 jours et son nombre de paris
--   gagnés. Un agent d'un bookmaker infiltré comme abonné n'avait qu'à
--   recouper ces pseudos avec sa propre base de comptes pour repérer les
--   joueurs à limiter.
--
--   Et c'est le vrai danger : tuer un surebet coûte peu à vos abonnés,
--   faire fermer leurs comptes les fait partir définitivement.
--
--   Le rang suffit à l'émulation. Le montant ne sert qu'à l'adversaire.
-- ═══════════════════════════════════════════════════════════════════════

drop view if exists public.leaderboard_7d;

create or replace view public.leaderboard_7d
with (security_invoker = off)
as
with gagnants as (
  select
    p.username,
    sum(coalesce((b.payload->>'profit')::numeric, 0)) as profit_reel
  from public.bets b
  join public.profiles p on p.id = b.user_id
  where b.status = 'won'
    and b.created_at >= now() - interval '7 days'
    and p.username is not null
  group by p.username
  having sum(coalesce((b.payload->>'profit')::numeric, 0)) > 0
)
select
  username,
  row_number() over (order by profit_reel desc) as rang,
  -- Un palier plutôt qu'un chiffre : on situe sans livrer le montant.
  case
    when profit_reel >= 20000 then 'excellent'
    when profit_reel >=  5000 then 'tres bon'
    when profit_reel >=  1000 then 'bon'
    else 'positif'
  end as palier
from gagnants
order by rang
limit 20;

revoke all on public.leaderboard_7d from anon;
grant select on public.leaderboard_7d to authenticated;

-- Vous, l'admin, gardez la vue chiffrée — mais elle n'est lisible que par
-- vous, jamais par l'API des abonnés.
create or replace function public.leaderboard_montants()
returns table (username text, profit numeric, paris bigint)
language sql
security definer
stable
set search_path = public
as $$
  select p.username,
         round(sum(coalesce((b.payload->>'profit')::numeric, 0))::numeric, 2),
         count(*)
  from public.bets b
  join public.profiles p on p.id = b.user_id
  where b.status = 'won'
    and b.created_at >= now() - interval '7 days'
    and p.username is not null
    and public.is_admin()
  group by p.username
  order by 2 desc
  limit 50;
$$;

revoke all on function public.leaderboard_montants() from public;
grant execute on function public.leaderboard_montants() to authenticated;


-- ═══════════════════════════════════════════════════════════════════════
-- B · COMPTES QUI CONSOMMENT SANS JAMAIS JOUER
--
--   Un infiltré a une signature simple : il paie, il lit tous les signaux,
--   et il ne fait jamais rien. Pas un pari enregistré, pas un mouvement de
--   caisse, pas un message.
--
--   ⚠️ CE N'EST PAS UNE PREUVE. Un débutant intimidé a exactement le même
--      profil, et c'est même le cas le plus fréquent. Traitez cette liste
--      comme une liste de gens à qui écrire — pas à exclure. Si c'est un
--      débutant, vous récupérez un abonné. Si c'est autre chose, le
--      silence répété vous le dira.
-- ═══════════════════════════════════════════════════════════════════════

create or replace function public.comptes_passifs()
returns table (
  username        text,
  email           text,
  inscrit_depuis  int,
  abonne          boolean,
  paris           bigint,
  mouvements      bigint,
  messages        bigint
)
language sql
security definer
stable
set search_path = public
as $$
  select
    p.username,
    p.email,
    greatest(0, extract(day from now() - p.created_at)::int),
    (p.sub_expires_at > now()),
    (select count(*) from public.bets     b where b.user_id = p.id),
    (select count(*) from public.bankroll k where k.user_id = p.id),
    (select count(*) from public.messages m where m.user_id = p.id)
  from public.profiles p
  where public.is_admin()
    and p.role = 'user'
    and p.sub_expires_at is not null          -- il a payé au moins une fois
    and p.created_at < now() - interval '7 days'
    and not exists (select 1 from public.bets b where b.user_id = p.id)
  order by p.created_at;
$$;

revoke all on function public.comptes_passifs() from public;
grant execute on function public.comptes_passifs() to authenticated;


-- ═══════════════════════════════════════════════════════════════════════
-- VÉRIFICATION
--   select * from public.leaderboard_7d;        -- plus aucun montant
--   select * from public.leaderboard_montants();-- chiffré, admin seulement
--   select * from public.comptes_passifs();     -- à contacter, pas à exclure
-- ═══════════════════════════════════════════════════════════════════════
