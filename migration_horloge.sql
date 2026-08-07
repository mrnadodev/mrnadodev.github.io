-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  NADOEDGE · Heure du serveur, lisible par le navigateur               ║
-- ║  Supabase → SQL Editor → Run.                                         ║
-- ╚══════════════════════════════════════════════════════════════════════╝
--
-- POURQUOI
--   created_at et expires_at sont posés par Postgres. L'âge d'un signal est
--   calculé dans le navigateur : si l'horloge de l'appareil dérive, l'âge
--   affiché est faux d'autant. Un téléphone d'entrée de gamme dérive
--   couramment de plusieurs minutes — et l'âge est justement l'indicateur
--   de fiabilité vendu à l'abonné.
--
--   On ne peut pas lire l'en-tête HTTP « Date » depuis le navigateur : le
--   CORS n'expose qu'une poignée d'en-têtes, et Date n'en fait pas partie.
--   Il faut donc que l'heure arrive dans le CORPS de la réponse.
--
-- CE QUE ÇA EXPOSE
--   Uniquement l'heure du serveur. Aucune donnée, aucun secret. C'est déjà
--   ce que révèle n'importe quelle réponse HTTP.

create or replace function public.server_now()
returns timestamptz
language sql
stable
as $$
  select now();
$$;

revoke all on function public.server_now() from public;
grant execute on function public.server_now() to anon, authenticated;

-- Vérification :
--   select public.server_now();
