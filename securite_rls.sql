-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOBET · DURCISSEMENT SÉCURITÉ (RLS bets / bankroll / profiles)      ║
-- ║  À exécuter dans Supabase → SQL Editor → New query → Run.              ║
-- ║  Objectif : chaque utilisateur ne voit QUE ses propres données.        ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ─────────────────────────────────────────────────────────────────────────
-- ÉTAPE 0 · DIAGNOSTIC — exécutez d'abord CETTE requête SEULE pour voir
--           l'état actuel. Repérez les tables avec rowsecurity = false
--           (= NON protégées) et les politiques trop larges (qual = 'true').
-- ─────────────────────────────────────────────────────────────────────────
-- select t.tablename, t.rowsecurity as rls_active,
--        p.policyname, p.cmd, p.qual
-- from pg_tables t
-- left join pg_policies p on p.tablename = t.tablename and p.schemaname='public'
-- where t.schemaname='public'
--   and t.tablename in ('bets','bankroll','profiles','signals','messages','payment_requests')
-- order by t.tablename, p.policyname;
--
-- ⚠️ Si vous voyez une politique avec qual = 'true' (ou 'expr: true') sur
--    bets/bankroll/profiles, c'est une FUITE : notez son policyname et
--    supprimez-la :   drop policy "nom_de_la_politique" on public.bets;

-- ─────────────────────────────────────────────────────────────────────────
-- ÉTAPE 1 · Fonction anti-récursion (indispensable pour les policies profiles)
--           SECURITY DEFINER => contourne la RLS, évite la récursion infinie.
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.is_admin()
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin');
$$;

-- ─────────────────────────────────────────────────────────────────────────
-- ÉTAPE 2 · BETS — chaque utilisateur ne lit/écrit QUE ses paris
-- ─────────────────────────────────────────────────────────────────────────
alter table public.bets enable row level security;
drop policy if exists bets_own on public.bets;
create policy bets_own on public.bets
  for all
  using      ( user_id = auth.uid() )
  with check ( user_id = auth.uid() );

-- ─────────────────────────────────────────────────────────────────────────
-- ÉTAPE 3 · BANKROLL — idem
-- ─────────────────────────────────────────────────────────────────────────
alter table public.bankroll enable row level security;
drop policy if exists bankroll_own on public.bankroll;
create policy bankroll_own on public.bankroll
  for all
  using      ( user_id = auth.uid() )
  with check ( user_id = auth.uid() );

-- ─────────────────────────────────────────────────────────────────────────
-- ÉTAPE 4 · PROFILES — lecture/écriture de SA ligne ; l'admin voit/gère tout.
--           (Le trigger de abonnement_surebets.sql empêche déjà un
--            non-admin de changer role/status/abonnement.)
-- ─────────────────────────────────────────────────────────────────────────
alter table public.profiles enable row level security;

drop policy if exists profiles_select on public.profiles;
create policy profiles_select on public.profiles
  for select using ( id = auth.uid() or public.is_admin() );

drop policy if exists profiles_insert on public.profiles;
create policy profiles_insert on public.profiles
  for insert with check ( id = auth.uid() );

drop policy if exists profiles_update on public.profiles;
create policy profiles_update on public.profiles
  for update using ( id = auth.uid() or public.is_admin() );

-- ─────────────────────────────────────────────────────────────────────────
-- ÉTAPE 5 · Unicité du pseudo (insensible à la casse) — supprime la
--           "race condition" du contrôle côté client.
--   ⚠️ Si des doublons existent déjà, cette commande échoue : nettoyez-les
--      d'abord (voir la requête commentée en dessous).
-- ─────────────────────────────────────────────────────────────────────────
create unique index if not exists uq_profiles_username
  on public.profiles ( lower(username) )
  where username is not null;

-- Pour détecter d'éventuels doublons AVANT de créer l'index :
-- select lower(username) u, count(*) from public.profiles
-- where username is not null group by 1 having count(*) > 1;

-- ─────────────────────────────────────────────────────────────────────────
-- FIN. Re-lancez la requête de DIAGNOSTIC (étape 0) : rls_active doit être
--      true partout, et il ne doit plus rester de politique qual = 'true'.
-- ─────────────────────────────────────────────────────────────────────────
