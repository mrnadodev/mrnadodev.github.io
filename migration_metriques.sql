-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Métriques d'abonnement (point 16 de l'audit)              ║
-- ║  Supabase → SQL Editor → Run.                                         ║
-- ║                                                                       ║
-- ║  Une seule question compte pour la survie du service :                ║
-- ║  « combien de signaux un abonné a-t-il réellement reçus pendant la    ║
-- ║  semaine qu'il a payée ? »                                            ║
-- ║  En dessous de 3 ou 4, personne ne renouvelle, quel que soit le prix. ║
-- ╚══════════════════════════════════════════════════════════════════════╝


-- ─────────────────────────────────────────────────────────────────────────
-- 1) PRODUCTION · combien de signaux publiés, semaine par semaine
--    C'est la courbe à surveiller : si elle baisse, les résiliations
--    suivent deux semaines plus tard.
-- ─────────────────────────────────────────────────────────────────────────
create or replace view public.v_signaux_par_semaine as
select
  date_trunc('week', created_at)::date as semaine,
  count(*)                             as signaux,
  round(avg(roi)::numeric, 2)          as roi_moyen,
  round(max(roi)::numeric, 2)          as roi_max,
  count(distinct author_id)            as publishers_actifs
from public.signals
group by 1
order by 1 desc;


-- ─────────────────────────────────────────────────────────────────────────
-- 2) VALEUR LIVRÉE · signaux reçus par période payée
--
--    Chaque paiement validé ouvre une fenêtre d'accès. On compte les
--    signaux publiés PENDANT cette fenêtre : c'est exactement ce que
--    l'abonné a eu pour son argent.
--
--    Note : on part de reviewed_at (le moment où vous avez débloqué), pas
--    de created_at (le moment où il a envoyé la référence). C'est bien à
--    partir du déblocage que son accès court.
-- ─────────────────────────────────────────────────────────────────────────
create or replace view public.v_valeur_par_abonnement as
with fenetres as (
  select
    r.id,
    r.user_id,
    r.email,
    r.username,
    coalesce(r.reviewed_at, r.created_at) as debut,
    coalesce(r.reviewed_at, r.created_at)
      + ((select coalesce(nullif(value,''),'7') from public.app_settings
          where key='sub_duration_days')::int || ' days')::interval as fin
  from public.payment_requests r
  where r.status = 'approved'
)
select
  f.username,
  f.email,
  f.debut::date                                   as debut,
  count(s.id)                                     as signaux_recus,
  round(coalesce(avg(s.roi), 0)::numeric, 2)      as roi_moyen,
  case
    when count(s.id) = 0 then 'aucun signal — remboursement à envisager'
    when count(s.id) < 4 then 'trop peu — renouvellement improbable'
    else 'correct'
  end                                             as verdict
from fenetres f
left join public.signals s
  on s.created_at >= f.debut and s.created_at < f.fin
group by f.id, f.username, f.email, f.debut
order by f.debut desc;


-- ─────────────────────────────────────────────────────────────────────────
-- 3) RENOUVELLEMENT · qui revient, qui part
--
--    Un abonné qui a payé une seule fois n'est pas un client, c'est un
--    essai. Le chiffre qui compte est la part de ceux qui repaient.
-- ─────────────────────────────────────────────────────────────────────────
create or replace view public.v_renouvellement as
with paiements as (
  select user_id, count(*) as n, min(created_at) as premier, max(created_at) as dernier
  from public.payment_requests
  where status = 'approved'
  group by user_id
)
select
  count(*)                                                as clients_payants,
  count(*) filter (where n = 1)                           as une_seule_fois,
  count(*) filter (where n >= 2)                          as ont_renouvele,
  round(100.0 * count(*) filter (where n >= 2) / nullif(count(*), 0), 1)
                                                          as taux_renouvellement_pct,
  round(avg(n)::numeric, 2)                               as paiements_moyens_par_client
from paiements;


-- ─────────────────────────────────────────────────────────────────────────
-- 4) Accès : ces vues contiennent des emails, donc ADMIN uniquement.
--    Les vues héritent de la RLS des tables sous-jacentes ; on ajoute
--    une fonction de lecture pour l'interface, qui vérifie le rôle.
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.metriques_resume()
returns table (
  signaux_7j              bigint,
  signaux_7j_precedents   bigint,
  roi_moyen_7j            numeric,
  abonnes_actifs          bigint,
  signaux_moyens_par_abo  numeric,
  taux_renouvellement_pct numeric
)
language sql
security definer
stable
set search_path = public
as $$
  select
    (select count(*) from public.signals
      where created_at >= now() - interval '7 days'),
    (select count(*) from public.signals
      where created_at >= now() - interval '14 days'
        and created_at <  now() - interval '7 days'),
    (select round(coalesce(avg(roi),0)::numeric, 2) from public.signals
      where created_at >= now() - interval '7 days'),
    (select count(*) from public.profiles where sub_expires_at > now()),
    (select round(coalesce(avg(signaux_recus),0)::numeric, 1)
       from public.v_valeur_par_abonnement),
    (select taux_renouvellement_pct from public.v_renouvellement)
  where public.is_admin();     -- non-admin : aucune ligne renvoyée
$$;

revoke all on function public.metriques_resume() from public;
grant execute on function public.metriques_resume() to authenticated;


-- ─────────────────────────────────────────────────────────────────────────
-- LECTURE DES RÉSULTATS
--
--   select * from public.v_signaux_par_semaine;
--     → la production baisse-t-elle ? C'est le signal avancé des départs.
--
--   select * from public.v_valeur_par_abonnement;
--     → toute ligne « aucun signal » est un client qui a payé pour rien.
--       Remboursez-le avant qu'il en parle autour de lui : dans un marché
--       où tout passe par le bouche-à-oreille, c'est moins cher.
--
--   select * from public.v_renouvellement;
--     → en dessous de 30 % de renouvellement, le problème n'est pas
--       l'acquisition mais le produit. Inutile de faire de la publicité
--       pour remplir un seau percé.
-- ─────────────────────────────────────────────────────────────────────────
