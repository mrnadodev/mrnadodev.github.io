# Déplacer le scanner sur le VPS

Objectif : le scanner tourne 24 h/24 sur le VPS, et votre PC garde une copie
complète de secours.

Comptez 20 à 30 minutes, dont l'essentiel en attente de la construction de
l'image Docker.

---

## Avant de commencer

Il vous faut, fournis par votre hébergeur :

- l'**adresse IP** du VPS
- le **nom d'utilisateur** (souvent `root` ou `ubuntu`)
- le **mot de passe** ou votre clé SSH

Ces informations ne doivent apparaître nulle part dans le dépôt.

---

## 1. Sauvegarder l'existant sur votre PC

Avant de déplacer quoi que ce soit. Dans PowerShell, depuis le dossier du
projet :

```powershell
$date = Get-Date -Format "yyyy-MM-dd"
$dest = "$HOME\nadoedge-sauvegarde-$date"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item surebet.db      $dest -ErrorAction SilentlyContinue
Copy-Item surebet\.env    "$dest\env-scanner.txt"
Write-Host "Sauvegarde dans $dest"
```

`surebet.db` contient vos 893 détections et votre carnet de bord. Le VPS
repartira sur une base neuve : cette copie est votre historique.

---

## 2. Se connecter au VPS

```powershell
ssh utilisateur@ADRESSE_IP
```

Si c'est la première fois, répondez `yes` à la question sur l'empreinte.

---

## 3. Lancer l'installation

Toujours dans la fenêtre SSH :

```bash
curl -fsSL https://raw.githubusercontent.com/mrnadodev/mrnadodev.github.io/dev/deploiement/installer_vps.sh -o installer_vps.sh
bash installer_vps.sh
```

Le script installe Docker, récupère le code, configure le pare-feu.

Il s'arrêtera en réclamant le fichier de configuration : c'est normal,
il ne peut pas deviner vos secrets. Passez à l'étape suivante.

> Si Docker vient d'être installé, le script vous demande de vous
> déconnecter et de vous reconnecter. Faites-le (`exit` puis `ssh` à
> nouveau), sinon Docker réclamera `sudo` à chaque commande.

---

## 4. Transférer la configuration

Le fichier `.env` contient le token Telegram : **il n'est pas dans le
dépôt, et il ne doit jamais y entrer.** On le copie directement.

Depuis PowerShell **sur votre PC** (pas dans la fenêtre SSH) :

```powershell
scp surebet\.env utilisateur@ADRESSE_IP:~/nadoedge/deploiement/.env
```

Puis relancez l'installation dans la fenêtre SSH :

```bash
bash installer_vps.sh
```

Cette fois il ira au bout : il génère un mot de passe Postgres aléatoire,
construit l'image et démarre les services.

---

## 5. Vérifier

```bash
cd ~/nadoedge/deploiement
docker compose -f docker-compose.vps.yml ps
docker compose -f docker-compose.vps.yml logs -f app
```

Vous devez voir les cycles de collecte défiler. `Ctrl+C` quitte l'affichage
des journaux sans arrêter le scanner.

Attendez qu'une alerte arrive sur Telegram. Si rien ne vient au bout d'une
heure, cherchez l'erreur dans les journaux.

---

## 6. Arrêter le scanner sur votre PC

Une fois le VPS confirmé : **fermez la fenêtre `Surveillance.bat`.**

Sinon les deux tournent en parallèle et vous recevrez chaque alerte en
double — sans savoir laquelle vient d'où.

---

## Le tableau de bord

Il n'a **aucune authentification**. Publié en clair sur internet, il
donnerait vos surebets gratuitement à qui trouve l'adresse IP. Il n'écoute
donc que sur le VPS lui-même, et on y accède par un tunnel.

Depuis votre PC :

```powershell
ssh -L 8000:127.0.0.1:8000 utilisateur@ADRESSE_IP
```

Laissez la fenêtre ouverte, puis ouvrez `http://localhost:8000` dans votre
navigateur.

---

## Les sauvegardes

**Sur le VPS**, un service dédié exporte la base chaque jour dans
`~/nadoedge/deploiement/sauvegardes/`, et efface celles de plus de 14 jours.

**Vers votre PC**, une fois par semaine :

```powershell
scp -r utilisateur@ADRESSE_IP:~/nadoedge/deploiement/sauvegardes "$HOME\nadoedge-sauvegardes-vps"
```

Une sauvegarde qui vit uniquement sur la machine qu'elle protège ne protège
de rien : si le VPS disparaît, elle disparaît avec.

---

## Mettre à jour le scanner plus tard

Quand on aura corrigé quelque chose :

```bash
cd ~/nadoedge
git pull origin dev
cd deploiement
docker compose -f docker-compose.vps.yml --env-file .env up -d --build
```

---

## Ce qui a changé par rapport au fichier d'origine

`surebet/docker-compose.yml` était prévu pour une machine locale. Tel quel
sur un VPS, il présentait trois problèmes :

**Postgres était publié sur le port 5432** avec le mot de passe `surebet`.
Sur une IP publique, les robots trouvent un 5432 ouvert en quelques heures.
La base n'est plus accessible que depuis les conteneurs.

**Le tableau de bord écoutait sur toutes les interfaces**, sans
authentification. Il est maintenant limité à `127.0.0.1`.

**Le mot de passe était écrit dans le fichier**, donc dans le dépôt. Il est
généré aléatoirement à l'installation et vit dans `.env`.

Deux ajouts au passage : `shm_size` à 512 Mo, sans quoi Chromium plante au
bout de quelques heures avec la mémoire partagée par défaut de Docker, et
une limite de taille sur les journaux, sans quoi ils remplissent le disque
en quelques semaines.
