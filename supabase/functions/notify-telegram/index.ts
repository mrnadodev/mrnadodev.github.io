// ╔══════════════════════════════════════════════════════════════════════╗
// ║  NADOBET · Edge Function « notify-telegram »                           ║
// ║  Envoie l'alerte Telegram quand un surebet est publié, SANS exposer    ║
// ║  le token (il vit dans les secrets Supabase, jamais dans le client).   ║
// ║                                                                        ║
// ║  Sécurité :                                                            ║
// ║   1. JWT utilisateur obligatoire (la clé anon seule est rejetée).      ║
// ║   2. Seuls les rôles 'admin' / 'publisher' peuvent déclencher l'envoi. ║
// ║   3. Message générique (aucun détail du surebet ne transite ici).      ║
// ╚══════════════════════════════════════════════════════════════════════╝
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const TELEGRAM_BOT_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "";
const TELEGRAM_CHAT_ID   = Deno.env.get("TELEGRAM_CHAT_ID") ?? "";
const SUPABASE_URL       = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE_KEY   = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req: Request) => {
  // Pré-vol CORS
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "Méthode non autorisée" }, 405);

  try {
    // 1) JWT utilisateur obligatoire
    const authHeader = req.headers.get("Authorization") ?? "";
    const jwt = authHeader.replace(/^Bearer\s+/i, "").trim();
    if (!jwt) return json({ error: "Non authentifié" }, 401);

    // Client admin (service role) — sert à valider l'utilisateur et lire son rôle.
    const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
      auth: { persistSession: false, autoRefreshToken: false },
    });

    const { data: userData, error: userErr } = await admin.auth.getUser(jwt);
    if (userErr || !userData?.user) return json({ error: "Session invalide" }, 401);
    const user = userData.user;

    // 2) Autorisation : seuls admin / publisher peuvent déclencher l'alerte
    const { data: profile } = await admin
      .from("profiles")
      .select("role")
      .eq("id", user.id)
      .single();
    const role = profile?.role ?? "user";
    if (role !== "admin" && role !== "publisher") {
      return json({ error: "Accès refusé (rôle insuffisant)" }, 403);
    }

    // 3) Config Telegram présente ?
    if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
      return json({ error: "Telegram non configuré (secrets manquants)" }, 500);
    }

    // 4) Envoi de l'alerte générique (aucun détail du surebet)
    const text =
      "🔔 Surebet détecté !\nVérifie vite ton dashboard NADOBET pour voir les détails. ⚽💰";
    const tgRes = await fetch(
      `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text }),
      },
    );
    const tgJson = await tgRes.json().catch(() => ({}));
    if (!tgRes.ok || tgJson?.ok === false) {
      return json({ error: "Telegram: " + (tgJson?.description ?? "échec d'envoi") }, 502);
    }

    return json({ ok: true });
  } catch (e) {
    return json({ error: String((e as Error)?.message ?? e) }, 500);
  }
});
