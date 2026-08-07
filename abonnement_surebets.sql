-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOBET · ABONNEMENT SUREBETS (paywall 7 jours renouvelable)          ║
-- ║  À exécuter UNE FOIS dans Supabase → SQL Editor → New query → Run.     ║
-- ║                                                                        ║
-- ║  ⚠️ C'EST CE SCRIPT QUI SÉCURISE LE PAYWALL.                           ║
-- ║  Sans lui, le blocage n'est que cosmétique (contournable en console).  ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ─────────────────────────────────────────────────────────────────────────
-- 0) IMPORTANT : déclarer l'admin dans la base (par email).
--    Le rôle 'admin' en base est requis pour valider les paiements et
--    passer les verrous RLS. Remplacez l'email si besoin.
-- ─────────────────────────────────────────────────────────────────────────
update public.profiles
set role = 'admin'
where lower(email) = lower('mrnado.trading@gmail.com');

-- ─────────────────────────────────────────────────────────────────────────
-- 1) Colonnes d'abonnement sur profiles
-- ─────────────────────────────────────────────────────────────────────────
alter table public.profiles add column if not exists sub_expires_at timestamptz;
alter table public.profiles add column if not exists sub_plan       text;

-- ─────────────────────────────────────────────────────────────────────────
-- 2) Table des demandes de paiement (paiement manuel MonCash / NatCash)
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.payment_requests (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references public.profiles(id) on delete cascade,
  email       text,
  username    text,
  plan        text default 'week',      -- 'week' (7 jours)
  amount      text,                      -- montant affiché (ex : '500 HTG')
  channel     text,                      -- 'MonCash' | 'NatCash'
  reference   text,                      -- n° de transaction / téléphone payeur
  status      text default 'pending',    -- 'pending' | 'approved' | 'rejected'
  created_at  timestamptz default now(),
  reviewed_at timestamptz,
  reviewed_by uuid
);
create index if not exists idx_payreq_status  on public.payment_requests(status);
create index if not exists idx_payreq_user    on public.payment_requests(user_id);

-- ─────────────────────────────────────────────────────────────────────────
-- 3) VERROU ANTI-ESCALADE (le plus important pour la sécurité)
--    Empêche un utilisateur de s'auto-abonner / s'auto-approuver / se
--    promouvoir en modifiant sa propre ligne profiles via l'API.
--    Un non-admin ne peut PAS changer : role, status, sub_expires_at, sub_plan.
-- ─────────────────────────────────────────────────────────────────────────
create or replace function public.protect_profile_privileges()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare _is_admin boolean;
begin
  select (role = 'admin') into _is_admin
  from public.profiles where id = auth.uid();

  if coalesce(_is_admin, false) = false then
    new.role           := old.role;
    new.status         := old.status;
    new.sub_expires_at := old.sub_expires_at;
    new.sub_plan       := old.sub_plan;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_protect_profile on public.profiles;
create trigger trg_protect_profile
  before update on public.profiles
  for each row execute function public.protect_profile_privileges();

-- ─────────────────────────────────────────────────────────────────────────
-- 4) PAYWALL sur la table des surebets (signals)
--    Politique RESTRICTIVE : s'ajoute (AND) aux politiques existantes.
--    => Seuls un abonné actif OU un rôle privilégié peuvent LIRE les surebets.
--    (On ne touche pas aux politiques d'INSERT existantes des publishers.)
-- ─────────────────────────────────────────────────────────────────────────
alter table public.signals enable row level security;

-- Lecture de base (utilisateur connecté). Filet de sécurité : garantit que
-- l'activation de RLS ne bloque pas tout si aucune politique n'existait.
-- N'ouvre PAS aux visiteurs anonymes (auth.uid() null => refusé).
drop policy if exists signals_base_read on public.signals;
create policy signals_base_read on public.signals
  for select using ( auth.uid() is not null );

drop policy if exists signals_paywall_select on public.signals;
create policy signals_paywall_select on public.signals
  as restrictive
  for select
  using (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid()
        and ( p.sub_expires_at > now()
              or p.role in ('admin','publisher','moderator') )
    )
  );

-- ─────────────────────────────────────────────────────────────────────────
-- 5) PAYWALL sur l'archive des surebets dans le chat (messages, room='surebets')
--    Les messages normaux restent visibles ; seuls les messages du salon
--    'surebets' exigent un abonnement actif.
-- ─────────────────────────────────────────────────────────────────────────
alter table public.messages enable row level security;

-- Lecture de base (utilisateur connecté), filet de sécurité comme ci-dessus.
-- Si vous aviez déjà des politiques de chat plus strictes, retirez cette ligne.
drop policy if exists messages_base_read on public.messages;
create policy messages_base_read on public.messages
  for select using ( auth.uid() is not null );

drop policy if exists messages_surebet_gate on public.messages;
create policy messages_surebet_gate on public.messages
  as restrictive
  for select
  using (
    room is distinct from 'surebets'
    or exists (
      select 1 from public.profiles p
      where p.id = auth.uid()
        and ( p.sub_expires_at > now()
              or p.role in ('admin','publisher','moderator') )
    )
  );

-- ─────────────────────────────────────────────────────────────────────────
-- 6) RLS sur payment_requests
-- ─────────────────────────────────────────────────────────────────────────
alter table public.payment_requests enable row level security;

-- l'utilisateur crée sa propre demande
drop policy if exists payreq_insert_own on public.payment_requests;
create policy payreq_insert_own on public.payment_requests
  for insert with check ( user_id = auth.uid() );

-- l'utilisateur lit ses demandes ; l'admin lit tout
drop policy if exists payreq_select_own_or_admin on public.payment_requests;
create policy payreq_select_own_or_admin on public.payment_requests
  for select using (
    user_id = auth.uid()
    or exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin')
  );

-- seul l'admin valide / refuse
drop policy if exists payreq_update_admin on public.payment_requests;
create policy payreq_update_admin on public.payment_requests
  for update using (
    exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin')
  );

-- ─────────────────────────────────────────────────────────────────────────
-- FIN. Vérification rapide (optionnel) :
--   select id, email, role, status, sub_expires_at from public.profiles order by created_at desc;
-- ─────────────────────────────────────────────────────────────────────────
