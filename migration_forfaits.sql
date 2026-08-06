-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Forfait mensuel + limite d'appareils                      ║
-- ║  Supabase → SQL Editor → Run.                                         ║
-- ╚══════════════════════════════════════════════════════════════════════╝


-- ═══════════════════════════════════════════════════════════════════════
-- A · FORFAIT MENSUEL
--
--   Un seul palier à 7 jours oblige à refaire l'effort de conversion
--   chaque semaine, et rend la trésorerie imprévisible. Un palier mensuel
--   avec remise donne le même revenu, quatre fois moins de frictions de
--   paiement, et de la visibilité sur les rentrées.
--
--   Tarif retenu : 1800 HTG pour 30 jours.
--   Un mois à la semaine coûterait 4,3 × 500 = 2150 HTG ; la remise est
--   donc de 16 %. Assez pour être attractive, pas au point de pousser vos
--   abonnés hebdomadaires actuels à basculer à perte.
--   Vous pouvez changer ces valeurs depuis le tableau de bord admin.
-- ═══════════════════════════════════════════════════════════════════════
insert into public.app_settings(key, value) values
  ('sub_price_month',         '1800 HTG'),
  ('sub_duration_days_month', '30')
on conflict (key) do nothing;


-- ═══════════════════════════════════════════════════════════════════════
-- B · LIMITE D'APPAREILS
--
--   Un abonnement partagé entre dix personnes, ce sont neuf abonnements
--   perdus. Le jeton Supabase porte un identifiant de session : on garde
--   les deux plus récents par compte et on refuse les signaux aux autres.
--
--   DEUX appareils, pas un : un utilisateur légitime a un téléphone et un
--   ordinateur. En bloquer un génère du support pour rien.
--
--   ⚠️ CONÇU POUR NE JAMAIS ENFERMER PERSONNE. Si le jeton ne porte pas
--      la revendication session_id, la politique laisse passer. Vérifiez
--      quand même, connecté à l'application :
--        select auth.jwt() ->> 'session_id';
--      Une valeur non nulle = la limite est réellement appliquée.
--      Une valeur nulle    = tout continue de fonctionner, sans limite.
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists public.user_devices (
  user_id    uuid not null references public.profiles(id) on delete cascade,
  session_id text not null,
  first_seen timestamptz default now(),
  last_seen  timestamptz default now(),
  primary key (user_id, session_id)
);

alter table public.user_devices enable row level security;

-- Chacun voit ses propres appareils ; l'admin voit tout (support).
drop policy if exists devices_read on public.user_devices;
create policy devices_read on public.user_devices
  for select using ( user_id = auth.uid() or public.is_admin() );

-- Se déconnecter d'un appareil : on peut retirer les siens.
drop policy if exists devices_delete_own on public.user_devices;
create policy devices_delete_own on public.user_devices
  for delete using ( user_id = auth.uid() or public.is_admin() );

-- L'écriture passe uniquement par claim_device() ci-dessous : pas de
-- politique d'INSERT/UPDATE, donc rien ne s'écrit directement par l'API.

create or replace function public.max_devices()
returns int
language sql
stable
set search_path = public
as $$
  select coalesce(
    nullif((select value from public.app_settings where key = 'max_devices'), '')::int,
    2);
$$;

insert into public.app_settings(key, value) values ('max_devices', '2')
on conflict (key) do nothing;

-- Appelée par l'application à chaque connexion : « cet appareil est le mien ».
-- Renvoie le nombre d'appareils évincés, pour informer l'utilisateur.
create or replace function public.claim_device()
returns int
language plpgsql
security definer
set search_path = public
as $$
declare _sid text; _evinces int := 0;
begin
  _sid := auth.jwt() ->> 'session_id';
  if _sid is null or _sid = '' then
    return 0;                                  -- pas de session_id : rien à faire
  end if;

  insert into public.user_devices(user_id, session_id)
  values (auth.uid(), _sid)
  on conflict (user_id, session_id) do update set last_seen = now();

  -- On ne garde que les N appareils vus le plus récemment.
  with trop_vieux as (
    select session_id from public.user_devices
    where user_id = auth.uid()
    order by last_seen desc
    offset public.max_devices()
  )
  delete from public.user_devices d
  using trop_vieux t
  where d.user_id = auth.uid() and d.session_id = t.session_id;

  get diagnostics _evinces = row_count;
  return _evinces;
end;
$$;

revoke all on function public.claim_device() from public;
grant execute on function public.claim_device() to authenticated;

-- Le verrou : lire les signaux exige un appareil reconnu.
-- Les trois échappatoires (rôle privilégié, jeton sans session_id, aucun
-- appareil encore enregistré) garantissent que personne n'est enfermé.
drop policy if exists signals_appareil_reconnu on public.signals;
create policy signals_appareil_reconnu on public.signals
  as restrictive
  for select
  using (
    exists (select 1 from public.profiles p
            where p.id = auth.uid()
              and p.role in ('admin','publisher','moderator'))
    or (auth.jwt() ->> 'session_id') is null
    or not exists (select 1 from public.user_devices d where d.user_id = auth.uid())
    or exists (select 1 from public.user_devices d
               where d.user_id = auth.uid()
                 and d.session_id = auth.jwt() ->> 'session_id')
  );


-- ═══════════════════════════════════════════════════════════════════════
-- VÉRIFICATION
--
--   -- La revendication existe-t-elle ? (connecté à l'application)
--   select auth.jwt() ->> 'session_id';
--
--   -- Qui se connecte depuis combien d'appareils ?
--   select p.username, p.email, count(*) as appareils
--   from public.user_devices d join public.profiles p on p.id = d.user_id
--   group by p.username, p.email order by 3 desc;
--
--   -- Pour lever la limite le temps d'un dépannage :
--   update public.app_settings set value = '99' where key = 'max_devices';
-- ═══════════════════════════════════════════════════════════════════════
