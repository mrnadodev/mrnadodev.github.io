# Piloter le VPS en SSH

Toutes les commandes se tapent **sur le serveur**, dans la fenêtre SSH.

Deux interpréteurs cohabitent, et c'est la source d'erreur la plus fréquente :
OpenSSH vous dépose dans **`cmd`**, alors que la gestion des tâches planifiées
exige **PowerShell**. Chaque commande ci-dessous porte son interpréteur.

| Prompt affiché | Vous êtes dans |
|---|---|
| `administrator@… C:\nadoedge>` | `cmd` |
| `PS C:\nadoedge>` | PowerShell |

Pour passer de l'un à l'autre : `powershell` pour entrer, `exit` pour revenir.

---

## Se connecter

```bash
ssh Administrator@154.210.206.227
```

Le mot de passe est celui du **serveur**, le même qu'en Bureau à distance.
Rien ne s'affiche pendant la frappe — ni astérisques ni points. C'est voulu.

Pour quitter : `exit`.

Si la connexion est refusée alors qu'elle fonctionnait, votre adresse publique
a probablement changé : la règle de pare-feu n'autorise qu'elle. Relevez la
nouvelle **sur votre PC** avec `Invoke-RestMethod https://api.ipify.org`, puis
depuis le Bureau à distance :

```powershell
Set-NetFirewallRule -Name sshd-perso -RemoteAddress "VOTRE.NOUVELLE.IP"
```

---

## Voir si tout va bien

**Le contrôle complet** — Supabase, horloge, migrations, dernière publication,
Telegram, tâches, sauvegardes, tests. À lancer en premier quand un doute
s'installe. *(cmd)*

```bash
cd C:\nadoedge && python outils\controle_sante.py
```

**L'état des tâches en un coup d'œil** *(PowerShell)*

```powershell
Get-ScheduledTask NADOEDGE-* | Select TaskName,State
```

**Mémoire et disque** *(cmd)* — le premier chiffre à regarder après une panne.

```bash
systeminfo | findstr /I "virtual virtuelle physical physique"
```

---

## Le scanner

**Démarrer** *(PowerShell)*

```powershell
Enable-ScheduledTask NADOEDGE-Scanner; Start-ScheduledTask NADOEDGE-Scanner
```

**Arrêter** *(PowerShell)* — il repartira au prochain démarrage de la machine.

```powershell
Stop-ScheduledTask NADOEDGE-Scanner
```

**Arrêter durablement** *(PowerShell)*

```powershell
Stop-ScheduledTask NADOEDGE-Scanner; Disable-ScheduledTask NADOEDGE-Scanner
```

**Son journal, en direct** *(PowerShell)* — `Ctrl+C` pour sortir.

```powershell
Get-Content C:\nadoedge\logs\scanner-football.log -Tail 40 -Wait
```

**Les erreurs seulement** *(PowerShell)*

```powershell
Select-String -Path C:\nadoedge\logs\scanner-football.log -Pattern "ERROR|Traceback" | Select -Last 20
```

**Un scan unique, au premier plan** *(cmd)* — c'est ici que les erreurs
s'affichent en clair, et que l'on voit combien de cotes chaque bookmaker rend.

```bash
cd C:\nadoedge && python -m surebet.main --scan --sport football
```

### Basketball

Il a sa propre tâche, et il est **désactivé** par défaut : un second collecteur,
c'est un second navigateur Chromium.

```powershell
Enable-ScheduledTask NADOEDGE-Scanner-Basket; Start-ScheduledTask NADOEDGE-Scanner-Basket
```

```powershell
Stop-ScheduledTask NADOEDGE-Scanner-Basket; Disable-ScheduledTask NADOEDGE-Scanner-Basket
```

---

## Le carnet : ce que le scanner a trouvé

**Bilan des sept derniers jours** *(cmd)*

```bash
cd C:\nadoedge && python outils\journal_scanner.py --rapport --jours 7
```

**Répétitions récentes** — utile si un même match revient trop souvent.

```bash
cd C:\nadoedge && python outils\journal_scanner.py --repetitions --heures 24
```

**Le poids de chaque bookmaker** — dans combien d'occasions chacun est
*indispensable*, c'est-à-dire lesquelles disparaîtraient sans lui.

```bash
cd C:\nadoedge && python outils\valeur_bookmaker.py --jours 30
```

---

## Diagnostic

**La mémoire dans le temps** *(PowerShell)* — la sonde écrit une ligne toutes
les 5 minutes. C'est la courbe, pas la photo, qui identifie une fuite.

```powershell
Get-Content C:\nadoedge\logs\memoire.csv -Tail 30
```

**Ce que le navigateur du serveur voit sur Paryaj Lakay** *(cmd)* — enregistre
aussi `logs\lakay.html` et une capture d'écran.

```bash
cd C:\nadoedge && python outils\diag_lakay.py
```

**Les processus les plus gourmands en mémoire validée** *(cmd)*

```bash
wmic process where "PageFileUsage > 300000" get Name,ProcessId,PageFileUsage
```

**Pourquoi une tâche s'est arrêtée** *(PowerShell)* — `LastTaskResult` à `0`
signifie une fin normale ; toute autre valeur est un plantage.

```powershell
Get-ScheduledTask NADOEDGE-Scanner | Get-ScheduledTaskInfo | Select LastRunTime,LastTaskResult,NumberOfMissedRuns
```

---

## Mettre à jour et entretenir

**Récupérer le code** *(cmd)*

```bash
cd C:\nadoedge && git pull origin dev
```

Un changement de code ne prend effet qu'au redémarrage du collecteur :

```powershell
Stop-ScheduledTask NADOEDGE-Scanner; Start-Sleep 3; Start-ScheduledTask NADOEDGE-Scanner
```

**Sauvegarder la base maintenant** *(cmd)* — une tâche `NADOEDGE-Sauvegarde`
le fait déjà automatiquement.

```bash
cd C:\nadoedge && python outils\sauvegarder_scanner.py
```

**Réparer les tâches planifiées** *(cmd)* — les reconstruit avec journal et
relance automatique. Relançable sans risque.

```bash
cd C:\nadoedge && powershell -NoProfile -ExecutionPolicy Bypass -File deploiement\reparer_taches_vps.ps1
```

---

## Libérer la mémoire

Le symptôme : `Virtual Memory: Available` tombe à quelques dizaines de mégaoctets,
le collecteur meurt avec le code 255, et PowerShell lui-même refuse de démarrer
avec l'erreur `800705af`.

**Regarder d'abord** *(cmd)*

```bash
systeminfo | findstr /I "virtual virtuelle"
```

**Tuer les navigateurs restés en vol** *(PowerShell)* — souvent suffisant, et
sans interruption de service : la tâche se relance seule dans les 5 minutes.

```powershell
Stop-ScheduledTask NADOEDGE-Scanner; Get-Process chrome*,chromium* -EA 0 | Stop-Process -Force; Start-Sleep 5; Start-ScheduledTask NADOEDGE-Scanner
```

**Redémarrer la machine** — dernier recours, une à deux minutes d'interruption.
Le scanner repart seul, son déclencheur étant le démarrage. *(cmd)*

```bash
shutdown /r /t 30 /c "Maintenance"
```

Votre session SSH se ferme d'elle-même. Reconnectez-vous après deux minutes.

---

## En cas de blocage

**Le SSH ne répond plus.** Passez par le Bureau à distance, puis :

```powershell
Get-Service sshd; Restart-Service sshd
```

**Rien ne répond, ni SSH ni RDP.** Utilisez la console de secours de votre
hébergeur — c'est le seul accès qui survit à un pare-feu mal réglé ou à une
machine saturée.

**Une commande PowerShell refuse de s'exécuter en SSH** avec
`is not recognized` : vous êtes dans `cmd`. Tapez `powershell` d'abord.
