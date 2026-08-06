-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · CORRECTIFS DE SÉCURITÉ (audit)                            ║
-- ║  À exécuter dans Supabase → SQL Editor → Run, dans cet ordre.         ║
-- ║                                                                       ║
-- ║  Le bloc 1 corrige une faille CRITIQUE : n'importe quel nouvel        ║
-- ║  inscrit peut actuellement se donner le rôle admin. Exécutez-le       ║
-- ║  aujourd'hui, avant tout le reste.                                    ║
-- ╚══════════════════════════════════════════════════════════════════════╝


-- ═══════════════════════════════════════════════════════════════════════
-- 1) CRITIQUE · Escalade de privilèges à l'inscription
--
--    Le problème, en trois faits qui se combinent :
--      · la ligne profiles est créée par le NAVIGATEUR (index.html), pas
--        par le serveur — donc son contenu vient du client ;
--      · la politique profiles_insert ne vérifie que « id = auth.uid() »,
--        elle ne dit rien des colonnes role / status / sub_expires_at ;
--      · le garde-fou protect_profile_privileges est BEFORE UPDATE,
--        il ne se déclenche donc jamais sur un INSERT.
--
--    Résultat : depuis la console du navigateur, un compte tout neuf fait
--      sb.from('profiles').insert({ id:<son uid>, role:'admin',
--                                   status:'approved',
--                                   sub_expires_at:'2099-01-01' })
--    et obtient l'administration complète : lecture de tous les profils,
--    de tous les signaux, validation de paiements, modification des prix.
--
--    On ferme la porte des deux côtés : le serveur crée lui-même la ligne,
--    et tout INSERT venant d'un non-admin est ramené aux valeurs sûres.
-- ═══════════════════════════════════════════════════════════════════════

-- 1.a · Le même garde-fou, appliqué aussi à l'INSERT.
create or replace function public.protect_profile_insert()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare _is_admin boolean;
begin
  select (role = 'admin') into _is_admin
  from public.profiles where id = auth.uid();

  -- Un non-admin n'impose jamais ces colonnes : valeurs sûres, point.
  if coalesce(_is_admin, false) = false then
    new.role           := 'user';
    new.status         := 'pending';
    new.sub_expires_at := null;
    new.sub_plan       := null;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_protect_profile_ins on public.profiles;
create trigger trg_protect_profile_ins
  before insert on public.profiles
  for each row execute function public.protect_profile_insert();

-- 1.b · Le serveur crée la ligne à l'inscription : le client n'a plus
--       de raison légitime d'insérer dans profiles.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare _uname text;
begin
  _uname := nullif(new.raw_user_meta_data->>'username', '');

  -- Un index unique protège le pseudo. S'il est déjà pris, on crée quand
  -- même le compte sans pseudo : faire échouer l'inscription entière pour
  -- ça laisserait l'utilisateur devant une erreur incompréhensible.
  -- L'application lui redemandera un pseudo à la première connexion.
  if _uname is not null and exists (
       select 1 from public.profiles where lower(username) = lower(_uname)
     ) then
    _uname := null;
  end if;

  insert into public.profiles (id, email, username, role, status)
  values (new.id, new.email, _uname, 'user', 'pending')
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists trg_on_auth_user_created on auth.users;
create trigger trg_on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 1.c · Vérification : cette requête doit renvoyer 0 ligne.
--       Si elle en renvoie, un compte s'est déjà auto-promu.
--   select id, email, username, role, status, sub_expires_at
--   from public.profiles
--   where role <> 'user'
--     and lower(email) <> lower('mrnado.trading@gmail.com');


-- ═══════════════════════════════════════════════════════════════════════
-- 2) ÉLEVÉ · Usurpation d'identité dans le chat
--
--    Le navigateur envoie lui-même username et sender_role dans le
--    message. Rien ne les vérifie côté serveur : un abonné ordinaire peut
--    poster en se présentant comme « NADOEDGE » avec le badge admin, ou
--    publier dans le salon surebets sous le nom d'un publisher.
--
--    On écrase ces champs avec la vérité de la base.
-- ═══════════════════════════════════════════════════════════════════════
create or replace function public.stamp_message_identity()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare _role text; _username text; _email text;
begin
  new.user_id := auth.uid();                 -- on ne poste que pour soi
  select role, username, email into _role, _username, _email
  from public.profiles where id = auth.uid();
  new.sender_role := coalesce(_role, 'user');
  new.username    := coalesce(_username, split_part(coalesce(_email,''), '@', 1));
  new.email       := _email;
  return new;
end;
$$;

drop trigger if exists trg_stamp_message on public.messages;
create trigger trg_stamp_message
  before insert on public.messages
  for each row execute function public.stamp_message_identity();

-- Écriture dans le salon « surebets » : réservée aux publishers et admins.
drop policy if exists messages_insert_rules on public.messages;
create policy messages_insert_rules on public.messages
  as restrictive
  for insert
  with check (
    room is distinct from 'surebets'
    or exists (select 1 from public.profiles p
               where p.id = auth.uid() and p.role in ('admin','publisher'))
  );


-- ═══════════════════════════════════════════════════════════════════════
-- 3) ÉLEVÉ · Publication de faux surebets
--
--    signals.author_id est fourni par le client. Vérifiez d'abord si une
--    politique d'INSERT existe (elle n'est dans aucun fichier du dépôt,
--    donc probablement créée à la main dans l'interface Supabase) :
--      select policyname, cmd, qual, with_check
--      from pg_policies where tablename = 'signals';
--
--    Si la colonne with_check vaut « true » sur l'INSERT, n'importe quel
--    utilisateur connecté peut publier de faux signaux — et vos abonnés
--    misent dessus.
-- ═══════════════════════════════════════════════════════════════════════
drop policy if exists signals_insert_publishers on public.signals;
create policy signals_insert_publishers on public.signals
  for insert
  with check (
    author_id = auth.uid()
    and exists (select 1 from public.profiles p
                where p.id = auth.uid() and p.role in ('admin','publisher'))
  );

drop policy if exists signals_write_admin on public.signals;
create policy signals_write_admin on public.signals
  for update using ( public.is_admin() ) with check ( public.is_admin() );

drop policy if exists signals_delete_admin on public.signals;
create policy signals_delete_admin on public.signals
  for delete using ( public.is_admin() );


-- ═══════════════════════════════════════════════════════════════════════
-- 4) MOYEN · Le code du coffre paiement est lisible par tous
--
--    app_settings est en lecture pour tout utilisateur connecté, et
--    pay_lock_code y est stocké en clair. N'importe quel abonné fait
--      sb.from('app_settings').select('*')
--    et lit le code censé protéger vos coordonnées bancaires.
--
--    On sort ce secret de la table lisible et on le compare côté serveur.
-- ═══════════════════════════════════════════════════════════════════════
create table if not exists public.admin_secrets (
  key   text primary key,
  value text not null
);
alter table public.admin_secrets enable row level security;
-- Aucune politique = personne ne lit cette table via l'API. Volontaire.

-- On déplace le code existant, puis on l'efface de la table publique.
insert into public.admin_secrets(key, value)
select 'pay_lock_code', value from public.app_settings where key = 'pay_lock_code'
on conflict (key) do update set value = excluded.value;
delete from public.app_settings where key = 'pay_lock_code';

-- Vérification du code sans jamais le renvoyer au navigateur.
create or replace function public.check_pay_lock(code text)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare _stored text;
begin
  if not public.is_admin() then return false; end if;
  select value into _stored from public.admin_secrets where key = 'pay_lock_code';
  if _stored is null or _stored = '' then return true; end if;   -- non configuré
  return _stored = code;
end;
$$;

create or replace function public.set_pay_lock(code text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_admin() then
    raise exception 'Réservé à l''administrateur';
  end if;
  insert into public.admin_secrets(key, value) values ('pay_lock_code', coalesce(code,''))
  on conflict (key) do update set value = excluded.value;
end;
$$;

revoke all on function public.check_pay_lock(text) from public;
revoke all on function public.set_pay_lock(text)   from public;
grant execute on function public.check_pay_lock(text) to authenticated;
grant execute on function public.set_pay_lock(text)   to authenticated;


-- ═══════════════════════════════════════════════════════════════════════
-- 5) MOYEN · Moisson d'adresses email
--
--    La connexion par pseudo appelle email_for_username(uname) AVANT
--    d'être authentifié — la fonction est donc ouverte aux anonymes. Un
--    script qui essaie des pseudos courants récupère les emails associés :
--    matière première d'une campagne d'hameçonnage sur vos abonnés.
--
--    Correctif : la fonction ne renvoie plus l'email, elle se contente de
--    faire la connexion possible côté serveur. Ici on la restreint et on
--    journalise ; l'idéal reste de retirer la connexion par pseudo.
-- ═══════════════════════════════════════════════════════════════════════
create table if not exists public.username_lookup_log (
  id         bigserial primary key,
  uname      text,
  at         timestamptz default now()
);
alter table public.username_lookup_log enable row level security;
-- Aucune politique : lisible seulement depuis le SQL Editor.

create or replace function public.email_for_username(uname text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare _email text; _recent int;
begin
  -- Freinage : au-delà de 20 recherches en 10 minutes, on refuse.
  select count(*) into _recent
  from public.username_lookup_log where at > now() - interval '10 minutes';
  if _recent > 20 then
    raise exception 'Trop de tentatives, réessayez plus tard';
  end if;

  insert into public.username_lookup_log(uname) values (uname);

  select email into _email from public.profiles
  where lower(username) = lower(uname) limit 1;
  return _email;   -- null si inconnu : ne révèle pas si le pseudo existe
end;
$$;


-- ═══════════════════════════════════════════════════════════════════════
-- 6) MOYEN · Une seule session à la fois (partage de compte)
--
--    Un abonnement à 500 HTG partagé entre dix personnes, c'est neuf
--    abonnements perdus. Le jeton Supabase porte un identifiant de
--    session : on enregistre celui du dernier appareil connecté et on
--    exige qu'il corresponde pour lire les signaux.
--
--    ⚠️ Vérifiez d'abord que vos jetons portent bien la revendication
--       session_id (Supabase GoTrue v2 et suivants) :
--         select auth.jwt() -> 'session_id';
--       Si le résultat est vide, n'appliquez PAS ce bloc : il couperait
--       l'accès à tout le monde.
-- ═══════════════════════════════════════════════════════════════════════
alter table public.profiles add column if not exists active_session   text;
alter table public.profiles add column if not exists active_seen_at   timestamptz;

-- Appelée par le client juste après la connexion : « c'est moi l'appareil actif ».
create or replace function public.claim_session()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.profiles
  set active_session = auth.jwt() ->> 'session_id',
      active_seen_at = now()
  where id = auth.uid();
end;
$$;
revoke all on function public.claim_session() from public;
grant execute on function public.claim_session() to authenticated;

-- À n'activer qu'après avoir vérifié session_id (voir l'avertissement ci-dessus) :
--
-- drop policy if exists signals_single_device on public.signals;
-- create policy signals_single_device on public.signals
--   as restrictive
--   for select
--   using (
--     exists (select 1 from public.profiles p
--             where p.id = auth.uid()
--               and ( p.role in ('admin','publisher','moderator')
--                     or p.active_session is null
--                     or p.active_session = auth.jwt() ->> 'session_id' ))
--   );


-- ═══════════════════════════════════════════════════════════════════════
-- 7) MOYEN · Multiplication de comptes pour rejouer l'essai gratuit
--
--    Avant d'accorder deux jours d'essai, il faut pouvoir dire « cette
--    personne les a déjà eus ». L'email seul ne suffit pas : les alias
--    Gmail (mon.nom+1@gmail.com, m.o.n.n.o.m@gmail.com) donnent une
--    infinité d'adresses distinctes pour une même boîte.
--
--    On normalise l'email et on enregistre l'essai sur cette forme
--    canonique. Le numéro de téléphone MonCash reste le meilleur verrou
--    (voir les notes dans la réponse).
-- ═══════════════════════════════════════════════════════════════════════
-- Gmail ignore les points et tout ce qui suit un « + » : on ramène donc
-- ces variantes à une seule et même adresse.
create or replace function public.canonical_email(addr text)
returns text
language sql
immutable
as $$
  select case
    when lower(split_part(addr,'@',2)) in ('gmail.com','googlemail.com')
      then replace(split_part(split_part(lower(addr),'@',1), '+', 1), '.', '') || '@gmail.com'
    else lower(addr)
  end;
$$;

create table if not exists public.trial_grants (
  canon_email text primary key,
  granted_at  timestamptz default now(),
  user_id     uuid
);
alter table public.trial_grants enable row level security;
-- Aucune politique : la table ne se lit que côté serveur.

-- Accorde l'essai une seule fois par boîte mail réelle.
create or replace function public.grant_trial(days int default 2)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare _email text; _canon text; _already int;
begin
  select email into _email from public.profiles where id = auth.uid();
  if _email is null then return 'Compte introuvable'; end if;

  _canon := public.canonical_email(_email);
  select count(*) into _already from public.trial_grants where canon_email = _canon;
  if _already > 0 then
    return 'Essai déjà utilisé pour cette adresse';
  end if;

  insert into public.trial_grants(canon_email, user_id) values (_canon, auth.uid());
  update public.profiles
  set sub_expires_at = greatest(coalesce(sub_expires_at, now()), now()) + (days || ' days')::interval,
      sub_plan = 'trial'
  where id = auth.uid();
  return 'ok';
end;
$$;
revoke all on function public.grant_trial(int) from public;
grant execute on function public.grant_trial(int) to authenticated;


-- ═══════════════════════════════════════════════════════════════════════
-- 8) FAIBLE · Inondation de demandes de paiement
--    Rien n'empêche d'insérer des milliers de lignes dans
--    payment_requests : la file de validation devient inutilisable.
-- ═══════════════════════════════════════════════════════════════════════
create or replace function public.limit_payment_requests()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare _recent int;
begin
  select count(*) into _recent from public.payment_requests
  where user_id = auth.uid() and created_at > now() - interval '1 hour';
  if _recent >= 5 then
    raise exception 'Trop de demandes envoyées. Attendez la validation de la précédente.';
  end if;
  new.user_id := auth.uid();
  return new;
end;
$$;

drop trigger if exists trg_limit_payreq on public.payment_requests;
create trigger trg_limit_payreq
  before insert on public.payment_requests
  for each row execute function public.limit_payment_requests();


-- ═══════════════════════════════════════════════════════════════════════
-- 9) CONTRÔLE FINAL · à relancer après tout ce qui précède
--
--   -- Aucune table publique ne doit apparaître sans RLS :
--   select tablename, rowsecurity from pg_tables
--   where schemaname='public' and rowsecurity = false;
--
--   -- Aucune politique ne doit être ouverte en grand (qual/with_check = true)
--   -- sur les tables sensibles :
--   select tablename, policyname, cmd, qual, with_check
--   from pg_policies
--   where schemaname='public'
--     and tablename in ('profiles','signals','messages','bets','bankroll',
--                       'payment_requests','payment_channels','app_settings','sponsors')
--   order by tablename, policyname;
--
--   -- Aucun compte ne doit avoir un rôle privilégié à votre insu :
--   select id, email, username, role, status, sub_expires_at
--   from public.profiles where role <> 'user' order by created_at;
-- ═══════════════════════════════════════════════════════════════════════
