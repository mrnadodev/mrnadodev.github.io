# Mettre le site sur Cloudflare Pages

Domaine acheté chez Namecheap, hébergement sur Cloudflare Pages, courrier
chez Namecheap Private Email.

Comptez une heure, dont l'essentiel en attente de propagation DNS.

---

## Pourquoi ce montage

**Cloudflare Pages** est gratuit, sans plafond de trafic, et **sans
restriction d'usage commercial** — contrairement au plan gratuit de Vercel,
dont les conditions réservent l'offre Hobby au non-commercial. Le fichier
`vercel.json` a donc été retiré du dépôt.

Il apporte aussi ce que GitHub Pages ne permettait pas : des **en-têtes
HTTP personnalisés**. Sans eux, votre écran de connexion peut être encadré
dans une page tierce, et vous ne maîtrisez pas la propagation de vos mises
à jour.

---

## 1. Créer le site sur Cloudflare

1. Compte gratuit sur `dash.cloudflare.com`
2. **Workers & Pages** → **Create** → onglet **Pages** → **Connect to Git**
3. Autoriser GitHub, choisir le dépôt `mrnadodev.github.io`
4. Réglages de build :

   | Champ | Valeur |
   |---|---|
   | Framework preset | **None** |
   | Build command | *(vide)* |
   | Build output directory | **/** |
   | Production branch | **main** |

Il n'y a rien à compiler : le site est un fichier HTML et un module
JavaScript.

Cloudflare publie sur `nadoedge.pages.dev`. Vérifiez que la page s'affiche
avant d'aller plus loin.

> **Branche de production : `main`.** Tant que la fusion `dev` → `main`
> n'est pas faite, Cloudflare publiera l'ancienne version — la même qu'aujourd'hui.
> C'est voulu : on change d'hébergeur d'abord, on met à jour ensuite.

---

## 2. Amener le domaine sur Cloudflare

Cloudflare a besoin de gérer le DNS du domaine.

1. Dans Cloudflare : **Add a site** → votre domaine → plan **Free**
2. Cloudflare affiche **deux serveurs de noms** (`xxx.ns.cloudflare.com`)
3. Chez **Namecheap** : *Domain List* → *Manage* → **Nameservers** →
   **Custom DNS** → coller les deux → enregistrer

La propagation prend de quelques minutes à quelques heures.

> **Le courrier d'abord.** Si vous avez déjà acheté Private Email chez
> Namecheap, notez ses enregistrements MX **avant** de changer les serveurs
> de noms. Une fois le DNS chez Cloudflare, il faudra les y recréer, sinon
> vous cessez de recevoir vos messages. Voir la section 4.

---

## 3. Brancher le domaine sur le site

Dans **Workers & Pages** → votre projet → **Custom domains** →
**Set up a domain** → saisir `nadoedge.com`, puis recommencer pour
`www.nadoedge.com`.

Cloudflare crée les enregistrements et le certificat automatiquement.

---

## 4. Le courrier Namecheap

Dans Cloudflare → **DNS** → **Records**, recréez ce que Namecheap indique
dans *Private Email* → *Setup*. En général :

| Type | Nom | Valeur | Priorité |
|---|---|---|---|
| MX | `@` | `mx1.privateemail.com` | 10 |
| MX | `@` | `mx2.privateemail.com` | 10 |
| TXT | `@` | `v=spf1 include:spf.privateemail.com ~all` | — |

**Les enregistrements MX doivent être en « DNS only » (nuage gris), jamais
en « Proxied » (nuage orange).** Le proxy de Cloudflare ne traite que le
web ; appliqué au courrier, il le fait disparaître sans message d'erreur.

Vérifiez ensuite les valeurs exactes chez Namecheap : elles évoluent, et
celles ci-dessus sont indicatives.

---

## 5. Prévenir Supabase du nouveau domaine

**C'est l'étape qu'on oublie, et elle casse les mots de passe oubliés.**

Supabase → **Authentication** → **URL Configuration** :

- **Site URL** : `https://nadoedge.com`
- **Redirect URLs** : ajouter `https://nadoedge.com/**` et
  `https://www.nadoedge.com/**`

Sans cela, les liens de confirmation d'inscription et de réinitialisation
de mot de passe continueront de pointer vers l'ancienne adresse.

---

## 6. Vérifier

Depuis un téléphone, pas seulement depuis votre PC :

- [ ] `https://nadoedge.com` affiche la page d'accueil
- [ ] Le cadenas est présent (certificat valide)
- [ ] Le calculateur de la page d'accueil donne un résultat
- [ ] La connexion fonctionne
- [ ] Un mot de passe oublié envoie un lien vers `nadoedge.com`
- [ ] Un message envoyé à `contact@nadoedge.com` arrive

Les en-têtes se contrôlent ainsi :

```powershell
curl.exe -sI https://nadoedge.com | findstr /I "content-security frame cache"
```

Vous devez voir `Content-Security-Policy`, `frame-ancestors 'none'` et
`Cache-Control: public, max-age=0, must-revalidate`.

---

## 7. Éteindre GitHub Pages

Une fois tout vérifié : dépôt GitHub → **Settings** → **Pages** →
Source → **None**.

Laisser les deux en ligne signifierait deux versions du site, dont une que
vous ne mettriez plus à jour.

---

## Ce que contient `_headers`

Le fichier à la racine du dépôt, lu automatiquement par Cloudflare Pages.

**`Content-Security-Policy`** limite les origines autorisées : les scripts
ne peuvent venir que de `cdnjs` et `jsdelivr`, les connexions que de votre
projet Supabase. Une injection ne pourrait donc pas exfiltrer de données
vers un serveur tiers.

Une réserve honnête : la politique autorise `'unsafe-inline'` pour les
scripts, parce que toute l'application est un script en ligne. Cela réduit
beaucoup la protection contre l'injection. La restriction des origines et
de `connect-src` garde en revanche toute sa valeur.

**`frame-ancestors 'none'`** empêche l'encadrement de la page dans un site
tiers — l'attaque classique contre un écran de connexion.

**`Cache-Control: must-revalidate`** sur `index.html` et `arbitrage.js` :
le navigateur redemande le fichier à chaque visite et ne le retélécharge
que s'il a changé. Sans cela, après une mise en ligne, une partie de vos
utilisateurs garderait l'ancienne version — et une version périmée de
`arbitrage.js` afficherait de mauvaises mises.

---

## Si quelque chose ne marche pas

**Page blanche** : ouvrez la console du navigateur. Un message
`Refused to load … Content Security Policy` signale une origine à ajouter
dans `_headers`. Les quatre connues sont `fonts.googleapis.com`,
`fonts.gstatic.com`, `cdnjs.cloudflare.com`, `cdn.jsdelivr.net`.

**Le courrier n'arrive plus** : vérifiez que les MX sont en nuage **gris**.

**Un ancien contenu s'affiche** : Cloudflare → **Caching** →
**Purge Everything**.
