-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · VÉRIFICATIONS D'AUDIT (points 2 et 3)                     ║
-- ║                                                                       ║
-- ║  Où l'exécuter :                                                      ║
-- ║    Supabase → votre projet → SQL Editor → New query                   ║
-- ║    → coller UNE requête à la fois → Run (ou Ctrl+Entrée)              ║
-- ║                                                                       ║
-- ║  Ces requêtes ne MODIFIENT rien : elles lisent et affichent.          ║
-- ║  Les commandes de correction sont plus bas, commentées : ne les       ║
-- ║  décommentez qu'après avoir lu le résultat.                           ║
-- ╚══════════════════════════════════════════════════════════════════════╝


-- ═══════════════════════════════════════════════════════════════════════
-- POINT 2 · Quelqu'un s'est-il déjà donné des privilèges ?
-- ═══════════════════════════════════════════════════════════════════════
--
-- COMMENT LIRE LE RÉSULTAT
--
--   · Une seule ligne, avec VOTRE email et role = 'admin'
--       → tout va bien, passez au point 3.
--
--   · Des lignes avec des emails que vous ne reconnaissez pas
--       → un compte s'est promu. Voir « CORRECTION » plus bas.
--
--   · Des comptes en role = 'publisher' ou 'moderator' que vous n'avez
--     PAS nommés vous-même → même conclusion.
--
--   · sub_expires_at très loin dans le futur (2030, 2099…) sur un compte
--     qui n'a jamais payé → il s'est offert l'abonnement.

select
  id,
  email,
  username,
  role,
  status,
  sub_expires_at,
  created_at
from public.profiles
where role <> 'user'
   or sub_expires_at > now() + interval '60 days'
order by created_at desc;


-- ── Combien de comptes au total, et combien de suspects ? ──────────────
select
  count(*)                                              as total_comptes,
  count(*) filter (where role = 'admin')                as admins,
  count(*) filter (where role = 'publisher')            as publishers,
  count(*) filter (where role = 'moderator')            as moderateurs,
  count(*) filter (where sub_expires_at > now())        as abonnes_actifs,
  count(*) filter (where sub_expires_at > now() + interval '60 days')
                                                        as abos_anormalement_longs
from public.profiles;


-- ── Recoupement : un abonnement actif SANS aucun paiement validé ? ─────
--    C'est la signature d'un abonnement obtenu sans payer.
--    (Normal pour les comptes que VOUS avez débloqués à la main.)
select
  p.email,
  p.username,
  p.role,
  p.sub_expires_at,
  count(r.id) filter (where r.status = 'approved') as paiements_valides
from public.profiles p
left join public.payment_requests r on r.user_id = p.id
where p.sub_expires_at > now()
  and p.role = 'user'
group by p.id, p.email, p.username, p.role, p.sub_expires_at
having count(r.id) filter (where r.status = 'approved') = 0
order by p.sub_expires_at desc;


-- ═══════════════════════════════════════════════════════════════════════
-- POINT 2 · CORRECTION — à n'exécuter que si la requête ci-dessus a
--           révélé des comptes que vous n'avez pas autorisés.
--           Retirez les deux tirets du début de ligne pour l'activer.
-- ═══════════════════════════════════════════════════════════════════════

-- Remet TOUT le monde en simple utilisateur, sauf votre compte admin.
-- Remplacez l'email si le vôtre est différent.
--
-- update public.profiles
-- set role = 'user'
-- where role <> 'user'
--   and lower(email) <> lower('mrnado.trading@gmail.com');

-- Annule les abonnements anormalement longs obtenus sans paiement.
-- Ajustez la liste des emails d'après le résultat de la requête de recoupement.
--
-- update public.profiles
-- set sub_expires_at = null, sub_plan = null
-- where lower(email) in ('email_suspect_1@exemple.com', 'email_suspect_2@exemple.com');

-- Après correction : changez votre mot de passe admin depuis l'application,
-- et déconnectez toutes les sessions existantes depuis
-- Supabase → Authentication → Users → votre compte → Sign out user.


-- ═══════════════════════════════════════════════════════════════════════
-- POINT 3 · Qui a le droit de publier un surebet ?
-- ═══════════════════════════════════════════════════════════════════════
--
-- COMMENT LIRE LE RÉSULTAT
--
--   Repérez la ligne où cmd = 'INSERT', puis regardez with_check :
--
--   · with_check contient « role in ('admin','publisher') » ou
--     « author_id = auth.uid() » → correct, rien à faire.
--
--   · with_check vaut « true »  → DANGER : tout compte connecté peut
--     publier de faux surebets. Appliquez la correction plus bas.
--
--   · AUCUNE ligne avec cmd = 'INSERT' → personne ne peut publier via
--     l'API. Si la publication fonctionne quand même dans l'application,
--     c'est que vous la faites avec un compte qui contourne la RLS :
--     vérifiez-le, c'est anormal.
--
--   · permissive = 'PERMISSIVE' signifie « ce droit s'ajoute aux autres » ;
--     'RESTRICTIVE' signifie « cette condition s'ajoute en ET ».

select
  policyname   as nom_politique,
  cmd          as operation,
  permissive   as type,
  roles        as pour_qui,
  qual         as condition_lecture,
  with_check   as condition_ecriture
from pg_policies
where schemaname = 'public'
  and tablename  = 'signals'
order by cmd, policyname;


-- ── La RLS est-elle seulement active sur cette table ? ─────────────────
--    rowsecurity doit valoir true. Si false, TOUTES les politiques
--    ci-dessus sont ignorées et la table est grande ouverte.
select tablename, rowsecurity as rls_active
from pg_tables
where schemaname = 'public'
  and tablename in ('signals','messages','profiles','bets','bankroll',
                    'payment_requests','payment_channels','app_settings','sponsors')
order by tablename;


-- ── Vue d'ensemble : une politique trop large quelque part ? ───────────
--    Toute ligne où condition = 'true' sur une table sensible est une fuite.
select
  tablename,
  policyname,
  cmd,
  coalesce(qual, with_check) as condition
from pg_policies
where schemaname = 'public'
  and tablename in ('signals','messages','profiles','bets','bankroll',
                    'payment_requests','payment_channels','app_settings')
  and (qual = 'true' or with_check = 'true')
order by tablename, policyname;


-- ═══════════════════════════════════════════════════════════════════════
-- POINT 3 · CORRECTION — si with_check vaut « true » sur l'INSERT,
--           ou si aucune politique d'INSERT n'existe.
--
--           C'est le bloc 3 de securite_audit.sql, repris ici pour
--           que vous puissiez l'appliquer seul.
-- ═══════════════════════════════════════════════════════════════════════

-- Remplacez d'abord la politique trop large par son vrai nom, relevé
-- dans la colonne nom_politique ci-dessus :
--
-- drop policy "nom_de_la_politique_trop_large" on public.signals;

-- Puis posez la bonne règle : on publie pour soi, et seulement si on est
-- publisher ou admin.
--
-- drop policy if exists signals_insert_publishers on public.signals;
-- create policy signals_insert_publishers on public.signals
--   for insert
--   with check (
--     author_id = auth.uid()
--     and exists (select 1 from public.profiles p
--                 where p.id = auth.uid() and p.role in ('admin','publisher'))
--   );

-- Après application : reconnectez-vous à l'application et publiez un
-- surebet de test. Si la publication échoue, c'est que votre compte n'a
-- pas le rôle attendu en base — vérifiez-le avec la requête du point 2.
