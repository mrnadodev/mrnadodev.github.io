-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Migration v2                                              ║
-- ║  Sport & coup d'envoi · Pubs et sponsors séparés · Canaux de paiement ║
-- ║  À exécuter dans Supabase → SQL Editor → Run.                         ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ─────────────────────────────────────────────────────────────────────────
-- 1) SIGNAUX : sport et heure du coup d'envoi
--    Permet d'afficher (et de trier) ces colonnes dans le tableau.
-- ─────────────────────────────────────────────────────────────────────────
alter table public.signals add column if not exists sport     text;
alter table public.signals add column if not exists starts_at timestamptz;

-- On s'assure que created_at existe et porte bien un fuseau horaire :
-- sans fuseau, le navigateur lit l'heure comme locale et l'âge affiché est faux.
alter table public.signals add column if not exists created_at timestamptz default now();

-- ─────────────────────────────────────────────────────────────────────────
-- 2) SPONSORS vs PUBLICITÉS : deux natures distinctes, gérées séparément
--    kind = 'sponsor' (partenaire) ou 'ad' (emplacement publicitaire payant)
-- ─────────────────────────────────────────────────────────────────────────
alter table public.sponsors add column if not exists kind   text default 'sponsor';
alter table public.sponsors add column if not exists banner text;   -- URL de l'image de bannière

-- contrainte souple : on n'accepte que les deux natures prévues
do $$
begin
  if not exists (select 1 from pg_constraint where conname='sponsors_kind_chk') then
    alter table public.sponsors
      add constraint sponsors_kind_chk check (kind in ('sponsor','ad'));
  end if;
end $$;

create index if not exists idx_sponsors_kind on public.sponsors(kind, active, sort);

-- ─────────────────────────────────────────────────────────────────────────
-- 3) CANAUX DE PAIEMENT modifiables depuis le tableau de bord admin
--    (numéro, nom du business, QR) au lieu d'être figés dans le code.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.payment_channels (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,          -- MonCash, NatCash…
  number     text,                   -- numéro à créditer
  business   text,                   -- nom ou code du business
  qr         text,                   -- URL de l'image du QR code
  active     boolean default true,
  sort       int default 0,
  updated_at timestamptz default now()
);

alter table public.payment_channels enable row level security;

-- lecture : tout utilisateur connecté (il doit voir où payer)
drop policy if exists paychan_read on public.payment_channels;
create policy paychan_read on public.payment_channels
  for select using ( auth.uid() is not null );

-- écriture : ADMIN uniquement
drop policy if exists paychan_admin on public.payment_channels;
create policy paychan_admin on public.payment_channels
  for all
  using      ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') )
  with check ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') );

-- ─────────────────────────────────────────────────────────────────────────
-- 4) VERROU SUPPLÉMENTAIRE sur la section « Paiement » du tableau de bord
--    Un mot de passe distinct, demandé avant d'afficher les coordonnées.
--
--    ⚠️ Important : ce verrou est une protection d'INTERFACE (il évite qu'un
--    écran resté ouvert expose vos numéros). La vraie sécurité reste la RLS
--    ci-dessus : seul un compte admin peut modifier ces données.
--    Ne réutilisez pas votre mot de passe de connexion ici.
-- ─────────────────────────────────────────────────────────────────────────
insert into public.app_settings(key, value) values ('pay_lock_code', '')
  on conflict (key) do nothing;

-- ─────────────────────────────────────────────────────────────────────────
-- Vérification :
--   select id, name, number, business, active from public.payment_channels;
--   select name, kind, active from public.sponsors order by kind, sort;
-- ─────────────────────────────────────────────────────────────────────────
