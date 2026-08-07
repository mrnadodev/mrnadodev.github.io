-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOBET · Migration — Contenu éditable (textes) + Police du site      ║
-- ║  À exécuter dans Supabase → SQL Editor → Run.                          ║
-- ║  Permet à l'admin de modifier les textes du site et la police.        ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ─────────────────────────────────────────────────────────────────────────
-- 1) TEXTES DU SITE (mini-CMS : clé -> texte)
--    Chaque texte éditable de l'UI porte un data-key ; l'app applique
--    l'override s'il existe dans cette table.
-- ─────────────────────────────────────────────────────────────────────────
create table if not exists public.site_content (
  key        text primary key,     -- ex : 'surebets.title', 'chat.rules', 'plan.name'
  value      text,
  updated_at timestamptz default now()
);

alter table public.site_content enable row level security;

-- lecture par tout le monde connecté
drop policy if exists site_content_read on public.site_content;
create policy site_content_read on public.site_content
  for select using ( auth.uid() is not null );

-- modification : ADMIN uniquement
drop policy if exists site_content_admin on public.site_content;
create policy site_content_admin on public.site_content
  for all
  using      ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') )
  with check ( exists(select 1 from public.profiles p where p.id=auth.uid() and p.role='admin') );

-- ─────────────────────────────────────────────────────────────────────────
-- 2) POLICE DU SITE (choisie par l'admin parmi une liste sûre)
--    Stockée dans app_settings (déjà protégée admin par migration_prix_sponsors.sql).
--    Exemples de valeurs : 'Inter', 'Poppins', 'Roboto', 'Montserrat', 'System'.
-- ─────────────────────────────────────────────────────────────────────────
insert into public.app_settings(key, value) values ('site_font', 'System')
  on conflict (key) do nothing;

-- (Rappel : app_settings a déjà RLS lecture=connecté / écriture=admin
--  via migration_prix_sponsors.sql. Exécutez ce fichier-là aussi.)

-- ─────────────────────────────────────────────────────────────────────────
-- FIN. Table vide au départ : l'app utilise ses textes par défaut tant que
--      l'admin n'a rien surchargé.
-- ─────────────────────────────────────────────────────────────────────────
