-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Correctifs — suite de l'audit                             ║
-- ║                                                                       ║
-- ║  Bloc A · Ménage dans les politiques qui se cumulent en OU            ║
-- ║  Bloc B · Le ROI est recalculé par le serveur (intégrité du produit)  ║
-- ║  Bloc C · Durée de validité bornée côté serveur                       ║
-- ║  Bloc D · Journal des publications                                    ║
-- ║                                                                       ║
-- ║  Supabase → SQL Editor → New query → coller un bloc → Run.            ║
-- ╚══════════════════════════════════════════════════════════════════════╝


-- ═══════════════════════════════════════════════════════════════════════
-- BLOC A · Politiques en double
--
--   Deux politiques PERMISSIVE se combinent avec OU : il suffit qu'une
--   seule accepte. Poser une règle stricte à côté d'une règle laxiste ne
--   durcit donc rien du tout — c'est la plus permissive qui décide.
--
--   Votre table signals porte aujourd'hui deux politiques d'INSERT et
--   deux de DELETE. On garde celles qui s'appuient sur le rôle en base,
--   on retire celles qui font double emploi.
--
--   ⚠️ AVANT : vérifiez que vous êtes bien 'admin' dans profiles (vous
--      l'êtes, l'audit l'a montré). APRÈS : publiez un surebet de test.
-- ═══════════════════════════════════════════════════════════════════════

-- Ancienne politique d'INSERT créée dans l'interface. On ne sait pas ce
-- que contient son with_check ; comme signals_insert_publishers couvre
-- déjà le cas correctement, on la retire plutôt que de la deviner.
drop policy if exists "Publication admin ou publisher" on public.signals;

-- Ancienne politique de DELETE : elle teste un email écrit en dur. Si
-- vous changez d'adresse un jour, la suppression casse sans prévenir.
-- signals_delete_admin fait la même chose via le rôle en base.
drop policy if exists "Suppression réservée à l'admin" on public.signals;

-- Politique de lecture redondante : son nom annonce un filtre sur les
-- surebets « actifs » qu'elle n'applique pas. signals_base_read dit déjà
-- la même chose, en plus clair.
drop policy if exists "Lecture des surebets actifs" on public.signals;

-- Contrôle : il doit rester exactement une politique par opération,
-- plus signals_paywall_select en RESTRICTIVE sur le SELECT.
--   select policyname, cmd, permissive, qual, with_check
--   from pg_policies where tablename='signals' order by cmd;


-- ═══════════════════════════════════════════════════════════════════════
-- BLOC B · Le ROI ne vient plus du navigateur
--
--   Aujourd'hui le ROI est calculé dans la page puis envoyé tel quel.
--   Rien ne vérifie qu'il correspond aux cotes. Un publisher distrait —
--   ou un compte compromis — annonce +8 % sur un signal qui en vaut −2 %,
--   et vos abonnés misent de l'argent réel dessus.
--
--   Le serveur recalcule à partir des cotes et écrase la valeur reçue.
--   Formule identique au calculateur : S = Σ(1/cote), ROI = (1−S)/S.
-- ═══════════════════════════════════════════════════════════════════════

create or replace function public.compute_signal_roi()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  _legs  jsonb;
  _s     numeric := 0;
  _n     int     := 0;
  _odd   numeric;
  _elem  jsonb;
  _roi   numeric;
begin
  -- La colonne peut être jsonb ou text : ce cast couvre les deux cas.
  begin
    _legs := new.legs::jsonb;
  exception when others then
    raise exception 'Jambes du surebet illisibles (JSON invalide)';
  end;

  if _legs is null or jsonb_typeof(_legs) <> 'array' then
    raise exception 'Un surebet doit contenir une liste de jambes';
  end if;

  for _elem in select * from jsonb_array_elements(_legs) loop
    -- Cote absente ou non numérique : la jambe ne compte pas.
    begin
      _odd := (_elem->>'odd')::numeric;
    exception when others then
      _odd := null;
    end;
    if _odd is not null and _odd > 1 then
      _s := _s + (1.0 / _odd);
      _n := _n + 1;
    end if;
  end loop;

  if _n < 2 then
    raise exception 'Il faut au moins deux cotes valides (supérieures à 1)';
  end if;

  _roi := (1 - _s) / _s * 100;

  if _roi <= 0 then
    raise exception
      'Ces cotes ne forment pas un surebet (ROI calculé : %). Publication refusée.',
      round(_roi, 2);
  end if;

  -- On écrase ce qu'a envoyé le navigateur : seule cette valeur fait foi.
  new.roi := round(_roi, 2);
  return new;
end;
$$;

drop trigger if exists trg_signal_roi on public.signals;
create trigger trg_signal_roi
  before insert or update of legs on public.signals
  for each row execute function public.compute_signal_roi();


-- ═══════════════════════════════════════════════════════════════════════
-- BLOC C · Durée de validité et horodatage
--
--   expires_at est calculé par le navigateur (Date.now() + minutes). Un
--   publisher peut donc poster un signal qui n'expire jamais, ou daté
--   d'hier. Et created_at venant du client fausserait l'âge affiché, qui
--   est justement l'indicateur de fiabilité vendu aux abonnés.
-- ═══════════════════════════════════════════════════════════════════════

create or replace function public.clamp_signal_dates()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.created_at := now();                       -- l'heure du serveur fait foi
  new.author_id  := coalesce(auth.uid(), new.author_id);

  if new.expires_at is null then
    new.expires_at := now() + interval '10 minutes';
  end if;
  -- Bornes : au moins 1 minute, au plus 2 heures.
  if new.expires_at < now() + interval '1 minute' then
    new.expires_at := now() + interval '1 minute';
  end if;
  if new.expires_at > now() + interval '2 hours' then
    new.expires_at := now() + interval '2 hours';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_signal_dates on public.signals;
create trigger trg_signal_dates
  before insert on public.signals
  for each row execute function public.clamp_signal_dates();


-- ═══════════════════════════════════════════════════════════════════════
-- BLOC D · Journal des publications
--
--   Qui a publié quoi, à quelle heure, avec quelles cotes. Si un abonné
--   conteste une perte, c'est votre seule pièce à conviction. Le journal
--   survit à la suppression du signal, et personne ne peut le réécrire.
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists public.signals_audit (
  id          bigserial primary key,
  signal_id   uuid,
  author_id   uuid,
  author_mail text,
  title       text,
  sport       text,
  roi         numeric,
  legs        jsonb,
  starts_at   timestamptz,
  expires_at  timestamptz,
  logged_at   timestamptz default now()
);

alter table public.signals_audit enable row level security;

-- Lecture : admin seulement. Écriture : personne via l'API — seul le
-- trigger ci-dessous écrit, et il tourne en security definer.
drop policy if exists signals_audit_read on public.signals_audit;
create policy signals_audit_read on public.signals_audit
  for select using ( public.is_admin() );

create or replace function public.log_signal_publication()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare _mail text;
begin
  select email into _mail from public.profiles where id = new.author_id;
  insert into public.signals_audit
    (signal_id, author_id, author_mail, title, sport, roi, legs, starts_at, expires_at)
  values
    (new.id, new.author_id, _mail, new.title, new.sport, new.roi,
     new.legs::jsonb, new.starts_at, new.expires_at);
  return new;
end;
$$;

drop trigger if exists trg_log_signal on public.signals;
create trigger trg_log_signal
  after insert on public.signals
  for each row execute function public.log_signal_publication();

-- Le journal ne se modifie ni ne s'efface, même par un admin.
create or replace function public.block_audit_rewrite()
returns trigger
language plpgsql
as $$
begin
  raise exception 'Le journal des publications ne peut pas être modifié';
end;
$$;

drop trigger if exists trg_audit_immutable on public.signals_audit;
create trigger trg_audit_immutable
  before update or delete on public.signals_audit
  for each row execute function public.block_audit_rewrite();


-- ═══════════════════════════════════════════════════════════════════════
-- BLOC E · « Ce pseudo est déjà pris » — un contrôle qui ne marchait pas
--
--   À l'inscription, l'application interroge profiles pour savoir si le
--   pseudo existe. Mais elle le fait AVANT d'être authentifiée, et la RLS
--   renvoie alors zéro ligne quoi qu'il arrive : le contrôle passe
--   toujours. L'utilisateur croit son compte créé, puis l'écriture du
--   profil échoue sur l'index unique — et il se retrouve sans pseudo.
--
--   Cette fonction répond par oui ou non, sans jamais rien révéler
--   d'autre. Contrairement à email_for_username, elle ne divulgue aucune
--   adresse : un pseudo est de toute façon visible dans le chat.
-- ═══════════════════════════════════════════════════════════════════════

create or replace function public.username_available(uname text)
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select not exists (
    select 1 from public.profiles where lower(username) = lower(uname)
  );
$$;

revoke all on function public.username_available(text) from public;
grant execute on function public.username_available(text) to anon, authenticated;


-- ═══════════════════════════════════════════════════════════════════════
-- VÉRIFICATION · publiez un surebet de test depuis l'application, puis :
--
--   select logged_at, author_mail, title, roi, expires_at
--   from public.signals_audit order by logged_at desc limit 5;
--
--   Le ROI du journal doit correspondre aux cotes que vous avez saisies.
--   Essayez ensuite de publier avec des cotes qui ne forment PAS un
--   surebet (ex. 2.10 et 1.80) : la publication doit être refusée.
-- ═══════════════════════════════════════════════════════════════════════
