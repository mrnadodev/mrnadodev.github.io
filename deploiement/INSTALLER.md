# Déplacer le scanner sur le VPS

Objectif : le scanner tourne 24 h/24 sur le VPS, et votre PC garde une copie
complète de secours.

Ce guide couvre **Windows Server 2022**. Un `docker-compose.vps.yml` reste
dans ce dossier pour un futur VPS Linux ; il ne sert pas ici.

Comptez 20 à 30 minutes, dont l'essentiel en installation de Python et de
Chromium.

---

## Ce qu'on installe, et pourquoi pas Docker

Sur Windows Server, Docker demanderait WSL2 ou un moteur payant, pour
faire tourner du Python qui tourne déjà très bien nativement. On reproduit
donc exactement l'installation de votre PC, avec une différence : le
scanner devient une **tâche planifiée** au lieu d'une fenêtre ouverte.

Une tâche planifiée démarre avec la machine, tourne **sans session ouverte**
— donc même quand vous fermez le Bureau à distance — et se relance toute
seule si elle tombe.

---

## 1. Sauvegarder l'existant sur votre PC

Avant de déplacer quoi que ce soit. Dans PowerShell, depuis le dossier du
projet :

```powershell
$date = Get-Date -Format "yyyy-MM-dd"
$dest = "$HOME\nadoedge-sauvegarde-$date"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item surebet.db   $dest -ErrorAction SilentlyContinue
Copy-Item surebet\.env "$dest\env-scanner.txt"
Write-Host "Sauvegarde dans $dest"
```

`surebet.db` contient vos détections et votre carnet de bord. Le VPS
repartira sur une base neuve : cette copie est votre historique.

---

## 2. Se connecter au VPS

Par le **Bureau à distance** (`mstsc`), avec l'adresse IP et le compte
fournis par votre hébergeur.

> **Avant toute chose, changez le mot de passe administrateur** s'il vous a
> été attribué par l'hébergeur. Un Windows Server exposé sur internet subit
> des milliers de tentatives de connexion par jour sur le port 3389 : c'est
> la première chose que les robots essaient. Voir la section sécurité en fin
> de document.

---

## 3. Lancer l'installation

Sur le VPS, ouvrez **PowerShell en tant qu'administrateur** (clic droit sur
le menu Démarrer → Terminal (admin)), puis :

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/mrnadodev/mrnadodev.github.io/dev/deploiement/installer_vps_windows.ps1" -OutFile installer.ps1
.\installer.ps1
```

Le script installe Python, Git, le code, Chromium, et configure le pare-feu.

Il s'arrêtera en réclamant le fichier de configuration : c'est normal, il
ne peut pas deviner vos secrets. Passez à l'étape suivante.

---

## 4. Transférer la configuration

`surebet\.env` contient le token Telegram : **il n'est pas dans le dépôt, et
il ne doit jamais y entrer.**

Le plus simple avec le Bureau à distance : ouvrez le fichier sur votre PC,
copiez son contenu, et collez-le dans un nouveau fichier sur le VPS à
`C:\nadoedge\surebet\.env`.

Ou, si OpenSSH est activé sur le VPS, depuis PowerShell **sur votre PC** :

```powershell
scp surebet\.env Administrateur@IP_DU_VPS:C:/nadoedge/surebet/.env
```

Puis relancez l'installation sur le VPS :

```powershell
.\installer.ps1
```

Cette fois il ira au bout : il enregistre la tâche planifiée et démarre le
scanner.

---

## 5. Vérifier

Sur le VPS :

```powershell
cd C:\nadoedge
.\Controle.bat
```

Tout doit être en `[  OK  ]`. Puis attendez qu'une alerte arrive sur
Telegram.

Pour voir l'état de la tâche :

```powershell
Get-ScheduledTask -TaskName NADOEDGE-Scanner | Get-ScheduledTaskInfo
```

`LastTaskResult` à `0` signifie que tout va bien. Une autre valeur, ou un
`LastRunTime` qui ne bouge pas, indique un problème.

---

## 6. Arrêter le scanner sur votre PC

Une fois le VPS confirmé : **fermez la fenêtre `Surveillance.bat`.**

Sinon les deux tournent en parallèle et vous recevrez chaque alerte en
double, sans savoir laquelle vient d'où — et votre carnet de bord comptera
les détections deux fois.

---

## Les sauvegardes

**Sur le VPS**, une tâche copie la base chaque nuit à 4 h dans
`C:\nadoedge\sauvegardes\`, et efface celles de plus de 14 jours.

**Vers votre PC**, une fois par semaine — par le Bureau à distance
(glisser-déposer) ou, si OpenSSH est activé :

```powershell
scp -r Administrateur@IP_DU_VPS:C:/nadoedge/sauvegardes "$HOME\nadoedge-sauvegardes-vps"
```

Une sauvegarde qui vit uniquement sur la machine qu'elle protège ne protège
de rien : si le VPS disparaît, elle disparaît avec.

---

## Mettre à jour le scanner plus tard

Sur le VPS, PowerShell administrateur :

```powershell
cd C:\nadoedge
git pull origin dev
Stop-ScheduledTask  -TaskName NADOEDGE-Scanner
Start-ScheduledTask -TaskName NADOEDGE-Scanner
```

Si les dépendances ont changé, relancez `.\installer.ps1` : il est
idempotent et ne casse rien.

---

## Sécurité du VPS Windows

Un Windows Server exposé sur internet est attaqué en permanence. Trois
mesures, par ordre d'importance :

**Le Bureau à distance ne doit pas être ouvert au monde.** Chez votre
hébergeur, restreignez le port 3389 à votre adresse IP. Si votre IP change,
un VPN ou un pare-feu applicatif est préférable à laisser ouvert.

**Un mot de passe administrateur long.** Vingt caractères minimum. C'est ce
qui est attaqué toute la journée.

**Le tableau de bord ne doit jamais être publié.** Il n'a aucune
authentification : accessible depuis internet, il donnerait vos surebets
gratuitement à qui trouve l'adresse IP. Le script bloque le port 8000, mais
vérifiez aussi le pare-feu de votre hébergeur — il est souvent en amont et
prioritaire.

---

## Si le VPS passe un jour sous Linux

`docker-compose.vps.yml`, dans ce même dossier, est prêt : Postgres non
publié, tableau de bord limité à `127.0.0.1`, mot de passe généré,
sauvegarde quotidienne intégrée. Il ne sert pas pour Windows Server.
