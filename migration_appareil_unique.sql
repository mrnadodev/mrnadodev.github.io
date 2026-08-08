-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Un seul appareil par abonné                               ║
-- ║                                                                       ║
-- ║  À exécuter dans Supabase → SQL Editor, APRÈS migration_forfaits.sql. ║
-- ║  Sans effet si on l'exécute deux fois.                                ║
-- ║                                                                       ║
-- ║  Ce que ça change :                                                   ║
-- ║   1. La limite passe de 2 appareils à 1.                              ║
-- ║   2. Les rôles privilégiés (admin, publisher, moderator) en sont      ║
-- ║      exemptés : l'administration se fait depuis plusieurs machines.   ║
-- ║   3. Une fonction permet à un appareil de savoir s'il est toujours     ║
-- ║      reconnu — c'est elle qui déclenche la déconnexion automatique.   ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ── 1. Un seul appareil ────────────────────────────────────────────────
insert into public.app_settings(key, value) values ('max_devices', '1')
on conflict (key) do update set value = '1';


-- ── 2. La revendication d'appareil ─────────────────────────────────────
-- Le changement par rapport à migration_forfaits.sql : les rôles
-- privilégiés enregistrent leur appareil mais n'évincent jamais les autres.
-- Sans cette exception, publier un surebet depuis le téléphone déconnecterait
-- l'administrateur de son poste — au moment précis où il en a besoin.
create or replace function public.claim_device()
returns int
language plpgsql
security definer
set search_path = public
as $$
declare _sid text; _evinces int := 0; _privilegie boolean;
begin
  _sid := auth.jwt() ->> 'session_id';
  if _sid is null or _sid = '' then
    return 0;                                  -- jeton sans session : rien à faire
  end if;

  insert into public.user_devices(user_id, session_id)
  values (auth.uid(), _sid)
  on conflict (user_id, session_id) do update set last_seen = now();

  select exists (select 1 from public.profiles p
                 where p.id = auth.uid()
                   and p.role in ('admin','publisher','moderator'))
    into _privilegie;
  if _privilegie then
    return 0;                                  -- l'administration reste multi-appareils
  end if;

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


-- ── 3. « Suis-je toujours l'appareil reconnu ? » ────────────────────────
-- Appelée périodiquement par l'application. Quand elle renvoie false,
-- l'appareil se déconnecte lui-même : c'est ce qui rend l'éviction visible.
-- Sans elle, l'appareil évincé gardait son écran ouvert indéfiniment et ne
-- se heurtait au mur qu'en tentant de lire un signal.
--
-- Les trois cas qui renvoient true sans vérifier garantissent que personne
-- n'est enfermé dehors par un effet de bord : jeton sans session_id (version
-- ancienne de Supabase Auth), rôle privilégié, ou aucun appareil encore
-- enregistré pour ce compte.
create or replace function public.device_still_valid()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select case
    when (auth.jwt() ->> 'session_id') is null
      or (auth.jwt() ->> 'session_id') = ''            then true
    when exists (select 1 from public.profiles p
                 where p.id = auth.uid()
                   and p.role in ('admin','publisher','moderator')) then true
    when not exists (select 1 from public.user_devices d
                     where d.user_id = auth.uid())     then true
    else exists (select 1 from public.user_devices d
                 where d.user_id = auth.uid()
                   and d.session_id = auth.jwt() ->> 'session_id')
  end;
$$;

revoke all on function public.device_still_valid() from public;
grant execute on function public.device_still_valid() to authenticated;


-- ═══════════════════════════════════════════════════════════════════════
-- VÉRIFICATION
--
--   -- La limite est-elle bien à 1 ?
--   select value from public.app_settings where key = 'max_devices';
--
--   -- Qui est enregistré sur combien d'appareils ?
--   select p.email, p.role, count(*) as appareils, max(d.last_seen) as vu_le
--   from public.user_devices d join public.profiles p on p.id = d.user_id
--   group by p.email, p.role order by appareils desc;
--
--   -- SI CETTE TABLE EST VIDE alors que des utilisateurs sont connectés,
--   -- le mécanisme est inerte : leur jeton ne porte pas de session_id.
--   -- Rien ne sera verrouillé, et personne ne sera déconnecté à tort.
--
--   -- Dépannage : rendre son accès à quelqu'un sans attendre.
--   -- delete from public.user_devices where user_id = '00000000-…';
-- ═══════════════════════════════════════════════════════════════════════
