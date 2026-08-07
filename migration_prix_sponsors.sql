-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOBET · Migration — Prix d'abonnement modifiable + Sponsors (pub)   ║
-- ║  À exécuter dans Supabase → SQL Editor → Run.                          ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ─────────────────────────────────────────────────────────────────────────
-- 1) PRIX D'ABONNEMENT DYNAMIQUE (modifiable par l'admin, plus en dur)
--    Stocké dans app_settings. La fenêtre de paiement lira ces valeurs.
-- ─────────────────────────────────────────────────────────────────────────
insert into public.app_settings(key, value) values ('sub_price', '500 HTG')
  on conflict (key) do nothing;
insert into public.app_settings(key, value) values ('sub_duration_days', '7')
  on conflict (key) do nothing;

-- app_settings : lecture par tout utilisateur connecté, ÉCRITURE réservée à l'admin
alter table public.app_settings enable row level security;

drop policy if exists app_settings_read on public.app_settings;
create policy app_settings_read on public.app_settings
  for select using ( auth.uid() is not null );

drop policy if exists app_settings_write_admin on public.app_settings;
create policy app_settings_write_admin on public.app_settings
  for all
  using      ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') )
  with check ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') );

-- ─────────────────────────────────────────────────────────────────────────
-- 2) SPONSORS / PUBLICITÉ (gérés par l'admin uniquement)
--    La section pub reste MASQUÉE tant que cette table est vide.
--    Réservé aux entreprises hors paris (télécoms, paiement, commerces).
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.sponsors (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  tagline    text,
  cta_label  text default 'Découvrir',
  url        text,            -- lien du sponsor
  logo       text,            -- lettre, emoji, ou URL d'image
  color      text,            -- dégradé CSS optionnel (ex : 'linear-gradient(...)')
  active     boolean default true,
  sort       int default 0,   -- ordre d'affichage dans le carrousel
  created_at timestamptz default now()
);
create index if not exists idx_sponsors_active on public.sponsors(active, sort);

alter table public.sponsors enable row level security;

-- lecture par tout utilisateur connecté (l'app filtre active=true)
drop policy if exists sponsors_read on public.sponsors;
create policy sponsors_read on public.sponsors
  for select using ( auth.uid() is not null );

-- création / modification / suppression : ADMIN uniquement (pas de promo gratuite)
drop policy if exists sponsors_admin on public.sponsors;
create policy sponsors_admin on public.sponsors
  for all
  using      ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') )
  with check ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') );

-- ─────────────────────────────────────────────────────────────────────────
-- FIN. La table sponsors est volontairement VIDE : rien ne s'affiche tant
--      que l'admin n'a pas ajouté un sponsor sous contrat.
-- ─────────────────────────────────────────────────────────────────────────
