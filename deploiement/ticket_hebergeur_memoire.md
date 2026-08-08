# Signalement à l'hébergeur — mémoire validée épuisée

Constaté le 8 août 2026 sur le VPS Windows Server 2022.

**Avant d'envoyer**, remplacez `<IP_DU_VPS>` et `<IDENTIFIANT_CLIENT>` par vos
valeurs. Ne les inscrivez pas dans ce fichier : le dépôt est public.

Envoyez la version anglaise si le support ne répond pas en français — la
plupart des hébergeurs nord-américains n'ont pas d'équipe francophone.

---

## Les faits, à joindre dans les deux cas

| Mesure | Au démarrage | Quelques heures plus tard |
|---|---|---|
| Mémoire validée utilisée | 2 516 Mo | **54 738 Mo** |
| Mémoire validée disponible | 20 011 Mo | **33 Mo** |
| Limite | 22 527 Mo | 54 771 Mo *(fichier d'échange étendu de 6 à 37,5 Go)* |
| Somme de tous les processus > 200 Mo | — | **< 1 Go** |

Les trois seuls processus notables au moment de la saturation :

```
python.exe    307 Mo
python.exe    277 Mo
MsMpEng.exe   350 Mo    (Windows Defender)
```

Pools noyau, mesurés au même moment : **non paginé 163 Mo**, **paginé 246 Mo**.
Aucun navigateur en cours d'exécution. Disque : 257 Go libres sur 322.

Conséquences observées : PowerShell refuse de démarrer avec
`0x800705AF` (ERROR_COMMITMENT_LIMIT), Python échoue par `MemoryError` en
lisant un fichier de 470 Ko, et les processus de service sont tués avec le
code de sortie 255.

`sc query vmmemctl` renvoie `STATE : 4 RUNNING`.

Le compteur `\VM Memory\Memory Ballooned` n'existe pas sur cette machine :
les VMware Tools y sont installés sans leur fournisseur de compteurs, je ne
peux donc pas mesurer le ballon depuis l'invité.

---

## Version française

> Objet : mémoire validée épuisée sans processus correspondant — VPS `<IP_DU_VPS>`
>
> Bonjour,
>
> Mon VPS Windows Server 2022 (`<IP_DU_VPS>`, compte `<IDENTIFIANT_CLIENT>`,
> 16 Go de RAM) épuise sa mémoire validée en quelques heures, alors qu'aucun
> processus de la machine ne la détient.
>
> Au redémarrage, la mémoire validée utilisée est de 2 516 Mo. Quelques heures
> plus tard, elle atteint 54 738 Mo sur une limite de 54 771 Mo, ne laissant
> que 33 Mo disponibles. Au même instant, la somme de tous les processus
> dépassant 200 Mo est inférieure à 1 Go — les trois plus gros étant deux
> processus Python à 307 et 277 Mo, et Windows Defender à 350 Mo. Les pools
> noyau sont normaux : 163 Mo non paginé, 246 Mo paginé. Le disque dispose de
> 257 Go libres, et le fichier d'échange s'est étendu de lui-même de 6 à
> 37,5 Go pour suivre la demande.
>
> Autrement dit : plus de 53 Go de mémoire validée sont réservés sans qu'aucun
> processus invité ne les porte. La machine devient alors inutilisable —
> PowerShell ne démarre plus (`0x800705AF`), Python échoue par `MemoryError`
> en lisant un fichier de 470 Ko, et mes services sont tués.
>
> Le pilote `vmmemctl` est actif (`sc query vmmemctl` → `RUNNING`), mais je ne
> peux pas mesurer le ballon depuis l'invité : les VMware Tools sont installés
> sans leur fournisseur de compteurs de performance.
>
> Mes questions :
>
> 1. L'hôte qui héberge ma machine est-il en sur-réservation mémoire ?
> 2. Le *ballooning* est-il actif sur mon instance ? Pouvez-vous me communiquer
>    la valeur de « Memory Ballooned » relevée côté hôte sur les dernières
>    24 heures ?
> 3. Pouvez-vous désactiver le ballooning ou appliquer une réservation mémoire
>    garantie sur mon instance ?
> 4. Si ce n'est pas la cause, pouvez-vous m'indiquer ce qui, du côté de
>    l'hyperviseur, peut consommer la mémoire validée d'un invité sans
>    apparaître dans ses processus ni dans ses pools noyau ?
>
> Je peux fournir les captures d'écran de chaque mesure.
>
> Cordialement,

---

## English version

> Subject: Guest commit charge exhausted with no matching process — VPS `<IP_DU_VPS>`
>
> Hello,
>
> My Windows Server 2022 VPS (`<IP_DU_VPS>`, account `<IDENTIFIANT_CLIENT>`,
> 16 GB RAM) exhausts its commit charge within hours, while no process on the
> machine accounts for it.
>
> After a reboot, commit charge in use is 2,516 MB. A few hours later it
> reaches 54,738 MB against a 54,771 MB limit, leaving 33 MB available. At that
> same moment, the sum of every process above 200 MB is under 1 GB — the three
> largest being two Python processes at 307 MB and 277 MB, and Windows Defender
> at 350 MB. Kernel pools are normal: 163 MB nonpaged, 246 MB paged. The disk
> has 257 GB free, and the pagefile grew on its own from 6 GB to 37.5 GB trying
> to keep up.
>
> In other words, more than 53 GB of commit charge is reserved with no guest
> process holding it. The machine then becomes unusable: PowerShell fails to
> start with `0x800705AF` (ERROR_COMMITMENT_LIMIT), Python raises `MemoryError`
> reading a 470 KB file, and my services are killed with exit code 255.
>
> The `vmmemctl` driver is active (`sc query vmmemctl` → `RUNNING`), but I
> cannot measure the balloon from inside the guest: VMware Tools are installed
> without their performance counter provider.
>
> My questions:
>
> 1. Is the host running my VM memory-oversubscribed?
> 2. Is ballooning active on my instance? Could you send me the
>    "Memory Ballooned" value as recorded on the host over the last 24 hours?
> 3. Can you disable ballooning, or apply a guaranteed memory reservation to my
>    instance?
> 4. If this is not the cause, could you tell me what on the hypervisor side can
>    consume a guest's commit charge without appearing in its processes or its
>    kernel pools?
>
> I can provide screenshots of every measurement.
>
> Best regards,

---

## Si l'hébergeur nie

Deux réponses fréquentes, et quoi répondre.

**« Votre application fuit. »** Le total de tous les processus est inférieur à
1 Go au moment où 53 Go sont réservés. Une application ne peut pas consommer
de la mémoire validée sans qu'elle lui soit attribuée. Demandez-leur de
désigner le processus.

**« C'est votre fichier d'échange. »** Il s'est étendu tout seul de 6 à
37,5 Go, sur un disque disposant de 257 Go libres. Windows a suivi la demande
autant qu'il pouvait ; il n'est pas la cause, il en est la trace.

Si le dialogue n'aboutit pas, la mesure décisive vous appartient : la sonde
installée par `reparer_taches_vps.ps1` enregistre la mémoire validée et les
principaux consommateurs toutes les 5 minutes. Une courbe qui monte sans
qu'aucun processus ne grossisse est un argument qu'aucun support ne peut
écarter.
