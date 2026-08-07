#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NADOEDGE · Installation du scanner sur un VPS Debian / Ubuntu        ║
# ║                                                                       ║
# ║  À exécuter SUR LE VPS, connecté en SSH :                             ║
# ║      bash installer_vps.sh                                            ║
# ║                                                                       ║
# ║  Le script est idempotent : le relancer ne casse rien.                ║
# ╚══════════════════════════════════════════════════════════════════════╝
set -euo pipefail

DOSSIER="${HOME}/nadoedge"
DEPOT="https://github.com/mrnadodev/mrnadodev.github.io.git"
BRANCHE="dev"

echo "=== NADOEDGE · installation du scanner ==="
echo

# ── 1. Docker ─────────────────────────────────────────────────────────
if command -v docker >/dev/null 2>&1; then
  echo "[ok] Docker déjà installé : $(docker --version)"
else
  echo "[..] Installation de Docker…"
  curl -fsSL https://get.docker.com | sh
  # Pouvoir lancer docker sans sudo à la prochaine connexion.
  sudo usermod -aG docker "$USER" || true
  echo "[ok] Docker installé. DÉCONNECTEZ-VOUS puis reconnectez-vous,"
  echo "     sinon 'docker' réclamera sudo, et relancez ce script."
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[..] Installation du greffon compose…"
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-compose-plugin
fi
echo "[ok] compose : $(docker compose version --short 2>/dev/null || echo '?')"

# ── 2. Le code ────────────────────────────────────────────────────────
if [ -d "${DOSSIER}/.git" ]; then
  echo "[..] Mise à jour du code…"
  git -C "${DOSSIER}" fetch --quiet origin
  git -C "${DOSSIER}" checkout --quiet "${BRANCHE}"
  git -C "${DOSSIER}" pull --quiet --ff-only origin "${BRANCHE}"
else
  echo "[..] Récupération du code…"
  git clone --quiet --branch "${BRANCHE}" "${DEPOT}" "${DOSSIER}"
fi
echo "[ok] Code dans ${DOSSIER} (branche ${BRANCHE})"

# ── 3. La configuration ───────────────────────────────────────────────
# Le .env NE VIENT PAS du dépôt : il contient des secrets. Il est copié
# depuis votre PC (voir INSTALLER.md), ou créé ici à partir du modèle.
CONF="${DOSSIER}/deploiement/.env"
if [ -f "${CONF}" ]; then
  echo "[ok] Configuration présente"
else
  echo "[!!] ${CONF} est absent."
  echo "     Copiez-le depuis votre PC avant de continuer :"
  echo "       scp surebet\\.env ${USER}@<IP_DU_VPS>:${CONF}"
  echo "     puis ajoutez-y une ligne POSTGRES_PASSWORD=<mot de passe long>."
  exit 1
fi

if ! grep -q '^POSTGRES_PASSWORD=..' "${CONF}"; then
  MDP="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  echo "POSTGRES_PASSWORD=${MDP}" >> "${CONF}"
  echo "[ok] Mot de passe Postgres généré (32 caractères aléatoires)"
fi

chmod 600 "${CONF}"
mkdir -p "${DOSSIER}/deploiement/sauvegardes"

# ── 4. Pare-feu ───────────────────────────────────────────────────────
# Le tableau de bord n'écoute que sur 127.0.0.1 et Postgres n'est pas
# publié, mais une règle explicite vaut mieux qu'une configuration juste.
if command -v ufw >/dev/null 2>&1; then
  echo "[..] Pare-feu : SSH seulement"
  sudo ufw --force reset >/dev/null 2>&1 || true
  sudo ufw default deny incoming >/dev/null
  sudo ufw default allow outgoing >/dev/null
  sudo ufw allow OpenSSH >/dev/null
  sudo ufw --force enable >/dev/null
  echo "[ok] ufw actif : seul SSH entre"
else
  echo "[..] ufw absent, pare-feu non configuré (facultatif)"
fi

# ── 5. Démarrage ──────────────────────────────────────────────────────
cd "${DOSSIER}/deploiement"
echo "[..] Construction de l'image (quelques minutes la première fois)…"
docker compose -f docker-compose.vps.yml --env-file .env build --quiet
echo "[..] Démarrage…"
docker compose -f docker-compose.vps.yml --env-file .env up -d

echo
echo "=== Terminé ==="
echo
echo "  Voir les journaux en direct :"
echo "    cd ${DOSSIER}/deploiement && docker compose -f docker-compose.vps.yml logs -f app"
echo
echo "  Vérifier que tout tourne :"
echo "    docker compose -f docker-compose.vps.yml ps"
echo
echo "  Tableau de bord (depuis VOTRE PC, tunnel SSH) :"
echo "    ssh -L 8000:127.0.0.1:8000 ${USER}@<IP_DU_VPS>"
echo "    puis ouvrez http://localhost:8000"
echo
