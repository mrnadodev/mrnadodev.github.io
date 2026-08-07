# Consulter le tableau de bord depuis n'importe où

Objectif : ouvrir la liste visuelle des surebets depuis votre téléphone ou
votre PC, sans exposer la page à internet.

---

## Le problème à résoudre

Le tableau de bord n'a **aucune authentification**. Publié tel quel, il
donnerait la liste de vos surebets — votre produit payant — à toute
personne qui trouve l'adresse. C'est pourquoi il n'écoute que sur
`127.0.0.1` et que son port est bloqué au pare-feu.

Ouvrir le port serait donc une mauvaise réponse. Il faut une adresse
publique **avec un contrôle d'accès devant**.

---

## La solution : tunnel Cloudflare + Access

Le tunnel ouvre une connexion **sortante** du VPS vers Cloudflare. Rien
n'est ouvert en entrée : le pare-feu reste fermé, et la machine reste
invisible depuis internet.

Cloudflare Access s'intercale devant la page et exige une identification
par e-mail avant de laisser passer. Gratuit jusqu'à 50 personnes.

**Prérequis** : le domaine doit être géré par Cloudflare — c'est déjà prévu
dans [HEBERGEMENT.md](HEBERGEMENT.md).

---

## 1. Installer le tunnel sur le VPS

PowerShell **administrateur** :

```powershell
$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
New-Item -ItemType Directory -Force "C:\cloudflared" | Out-Null
Invoke-WebRequest -Uri $url -OutFile "C:\cloudflared\cloudflared.exe"
& "C:\cloudflared\cloudflared.exe" --version
```

---

## 2. Créer le tunnel côté Cloudflare

Dans le tableau de bord Cloudflare : **Zero Trust** → **Networks** →
**Tunnels** → **Create a tunnel** → type **Cloudflared** → nommez-le
`nadoedge-vps`.

Cloudflare affiche une commande d'installation contenant un jeton. Copiez
la partie `--token eyJ…` et lancez sur le VPS :

```powershell
& "C:\cloudflared\cloudflared.exe" service install VOTRE_JETON
```

Le tunnel devient un service Windows : il démarre avec la machine et se
relance seul.

---

## 3. Publier la page

Toujours dans Cloudflare, onglet **Public Hostname** du tunnel :

| Champ | Valeur |
|---|---|
| Subdomain | `scanner` |
| Domain | `nadoedge.com` |
| Service type | `HTTP` |
| URL | `127.0.0.1:8000` |

`https://scanner.nadoedge.com` pointe désormais sur votre VPS — mais la
page n'est pas encore protégée. **Ne vous arrêtez pas ici.**

---

## 4. Mettre l'authentification devant

**Zero Trust** → **Access** → **Applications** → **Add an application** →
**Self-hosted** :

- Nom : `Tableau de bord NADOEDGE`
- Domaine : `scanner.nadoedge.com`
- Politique : **Allow**, règle **Emails** → votre adresse

À chaque visite, Cloudflare envoie un code à cet e-mail. Sans le code,
personne n'atteint la page — pas même en connaissant l'adresse exacte.

C'est cette étape qui rend l'ensemble acceptable. Sans elle, vous auriez
simplement publié vos surebets avec une adresse plus jolie.

---

## 5. Faire tourner le tableau de bord en permanence

Le tunnel ne sert à rien si la page n'est pas démarrée. Une tâche
planifiée, comme pour le scanner :

```powershell
$t = "NADOEDGE-Dashboard"
if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $t -Confirm:$false
}
Register-ScheduledTask -TaskName $t `
  -Action (New-ScheduledTaskAction -Execute (Get-Command python).Source `
           -Argument "-m uvicorn surebet.dashboard.app:app --host 127.0.0.1 --port 8000 --log-level warning" `
           -WorkingDirectory "C:\nadoedge") `
  -Trigger (New-ScheduledTaskTrigger -AtStartup) `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -RestartInterval (New-TimeSpan -Minutes 2) -RestartCount 999 `
             -ExecutionTimeLimit ([TimeSpan]::Zero)) `
  -User "SYSTEM" -RunLevel Highest
Start-ScheduledTask -TaskName $t
```

> **Ce que ça coûte.** Le tableau de bord fait son PROPRE scan des
> bookmakers à chaque chargement de page, en plus du collecteur. Le laisser
> tourner en permanence double le trafic vers eux — et un bookmaker qui
> voit trop de requêtes finit par bloquer l'adresse IP.
>
> Si vous ne le consultez qu'occasionnellement, ne créez pas cette tâche :
> lancez-le à la demande par le menu **Scanner**, choix `9`.

---

## En attendant le domaine

Deux options immédiates.

**Le tunnel éphémère** — une adresse aléatoire, sans compte ni domaine :

```powershell
& "C:\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8000
```

Cloudflare affiche une adresse en `.trycloudflare.com`, valable tant que la
fenêtre reste ouverte.

**Attention : aucune authentification.** L'adresse est imprévisible, mais
quiconque l'obtient voit vos surebets. Acceptable pour un coup d'œil depuis
votre téléphone, pas pour un usage régulier.

**Le tunnel SSH** — si OpenSSH est actif sur le VPS, depuis votre PC :

```powershell
ssh -L 8000:127.0.0.1:8000 Administrateur@IP_DU_VPS
```

Puis `http://localhost:8000` dans votre navigateur. Chiffré, sans rien
publier — mais ce n'est pas un lien, et ça ne marche pas depuis un
téléphone.

---

## Vérifier

- [ ] `https://scanner.nadoedge.com` demande un code par e-mail
- [ ] Le code reçu donne accès à la page
- [ ] Depuis une navigation privée, l'accès est refusé sans le code
- [ ] Le port 8000 reste injoignable directement depuis internet

Ce dernier point se vérifie depuis votre PC :

```powershell
Test-NetConnection -ComputerName IP_DU_VPS -Port 8000
```

`TcpTestSucceeded : False` est le résultat attendu.
