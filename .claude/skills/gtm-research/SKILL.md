---
name: gtm-research
description: Opération d'enrichissement GTM Vision P&L, lancée à la main par Jonathan. Trouve le décideur réel de chaque boutique (fondateur, dirigeant, ops, finance) et son email nominatif vérifié, ou ajoute de nouveaux prospects Shopify FR/CH/BE, puis écrit le journal et projette le CRM. Clay en premier ; sans crédits, bascule sur la recherche sans Clay (registres officiels + vérification SMTP sans envoi). Utiliser quand Jonathan dit « enrichis le CRM », « trouve les décideurs », « trouve-moi N prospects », « remplace Clay », ou relance l'opération de recherche.
---

# Opération de recherche GTM

Aucun envoi, aucune lecture Gmail : cette opération ne touche que le journal (par
`gtm.py`) et le CRM (par projection). Un seul acteur à la fois : ne pas la lancer pendant
un `gtm-check`. Lire `docs/RESEARCH.md` (règles de preuve et outils) avant de commencer.

Chemins : moteur `racine de ce dépôt`,
CRM `C:\dev\gtm-crm`. Dossier de travail du jour : `local/research/AAAA-MM-JJ/` (hors Git).

## Économie du forfait — à respecter pendant toute l'opération

- **Les scripts font le travail mécanique.** Ne lire que leurs sorties compactes
  (`targets`, `summarize`, `verify`, `simulate`), jamais un JSON brut ni une page entière.
- **Pas d'outil Workflow, pas de fan-out.** Par défaut, tout se fait dans la session.
  Si plus de 30 boutiques demandent de la recherche web, lancer **au plus 2 sous-agents
  en même temps**, chacun sur un **gros lot de 15 à 25 boutiques**, jamais un agent par
  boutique. Leur donner les lignes `summarize` du lot et la règle de preuve ; leur faire
  rendre uniquement le fichier de décisions (format plus bas). Ils ne lancent ni
  `gtm.py`, ni Gmail, ni écriture CRM.
- **Clay coûte cher en contexte** (15 à 20 k tokens par réponse) : 10 domaines par
  recherche, enrichissement limité aux `entityIds` choisis, lecture par
  `get-task-context` avec `entityIds`. Ne jamais relancer une recherche déjà faite.
- **Recherche web** : au plus une requête par boutique, seulement pour les domaines
  « accepte-tout » ou inconnus. Un résumé de moteur n'est pas une source : confirmer
  l'adresse sur la page citée (`curl … | grep -o …`) avant de la retenir.
- **Navigateur** : seulement pour les extraits du registre suisse (`get_page_text`),
  onglet fermé ensuite.

## 1. Préflight

```bash
python -X utf8 -B scripts/gtm.py status
python -X utf8 -B scripts/gtm.py recover
python -X utf8 scripts/research.py targets local/research/AAAA-MM-JJ/targets.json
```

Arrêter si `emergency_stop` est vrai ou si `uncertain_sends` n'est pas vide. `targets`
liste les fiches sans adresse nominative et les boutiques déjà contactées sur une boîte
partagée sans décideur. Pour de nouveaux prospects, aller directement en section 5.

## 2. Clay d'abord

Premier réflexe, tant qu'il reste des crédits :

1. `search-contacts` par lots de 10 domaines, `dslQuery` =
   `select from people limit 5 by clay_company_id limit 50`. Le DSL refuse tout filtre de
   poste (`title`, `job_title`, `current_job_title`, `latest_experience_title`) : trier
   soi-même sur `latest_experience_company` et `latest_experience_title`.
2. `search-contacts-by-name` : 2 noms par appel au maximum (au-delà, délai dépassé).
3. `add-contact-data-points` type `Email` avec les seuls `entityIds` retenus, puis
   `get-task-context` avec ces `entityIds`.
4. Appels en série : Clay renvoie souvent 503 ou « too many concurrent requests ».
   Réessayer plus tard, pas en parallèle.
5. Refuser un email Clay sur un domaine étranger à la marque (agence, autre société),
   sauf si le registre montre que ce domaine appartient à la société qui exploite la boutique.

**Bascule** : dès la réponse « Credits are exhausted » (ou si Jonathan l'annonce), garder
les résultats déjà payés et traiter le reste avec la section 3. Le signaler dans le rapport.

## 3. Sans Clay

```bash
D=local/research/AAAA-MM-JJ
python -X utf8 scripts/research.py crawl $D/targets.json $D/crawl.json
python -X utf8 scripts/research.py registry $D/crawl.json $D/registry.json --names $D/names.json
python -X utf8 scripts/research.py summarize $D/crawl.json $D/registry.json $D/summary.json
```

- `names.json` (facultatif) : `{"rang": "raison sociale ou SIREN"}` pour les sites sans
  numéro. Écarter les homonymes (activité ou ville sans rapport avec la marque).
- Suisse : `summarize` donne le lien de l'extrait cantonal ; y lire la direction et les
  signatures dans le navigateur.
- Choisir par boutique 1 à 3 personnes : dirigeant légal ou fondateur, puis ops,
  logistique ou finance. Écrire `people.json` :
  `{"54": {"domains": ["marque.example.invalid"], "people": ["Prénom Nom"]}}`, avec le
  domaine des adresses publiées s'il diffère du site (pays, groupe, ancienne marque).

```bash
python -X utf8 scripts/research.py candidates $D/people.json $D/candidates.json
python -X utf8 scripts/research.py verify $D/candidates.json $D/verify.json
```

`verify` imprime par domaine les adresses `valide` et signale les domaines
« accepte-tout ». Pour ceux-là et les `inconnu`, une seule recherche web par boutique.
Une adresse n'est retenue que publiée par la personne ou `valide`.

## 4. Écrire le journal puis le CRM

Fichier de décisions (`$D/decisions.json`), une entrée par boutique traitée :

```json
[{"rank": 54, "person": "Prénom Nom — gérant ; logistique : Autre Nom (autre@marque.example.invalid)",
  "email": "prenom@marque.example.invalid", "proof": "smtp",
  "source": "https://recherche-entreprises.api.gouv.fr (registre FR) SIREN 000000000",
  "checks": "Registre : 50-99 salariés (2023)"}]
```

`proof` vaut `smtp`, `published` (mettre l'URL dans `source`), `fallback` (adresse de la
boutique gardée faute de mieux) ou `none`. `checks` ne sert qu'aux fiches jamais
contactées : effectif, CA, alertes (« À écarter : … » retire la fiche des prochaines cibles).
Sur une fiche déjà contactée, seul le décideur est ajouté ; l'adresse de l'envoi ne bouge pas.

Téléphone (toujours, demande du 30/09/2026) : `python -X utf8 scripts/research.py phones
$D/shops.json $D/phones.json` sur `[{"company", "site", "country"}]`, puis ajouter à chaque
décision ou prospect `"phone"` et `"phone_source"` (URL de la page lue). Seul un numéro
publié par la boutique, ou par la personne pour son activité, est retenu (docs/RESEARCH.md).

```bash
python -X utf8 scripts/research.py draft-updates $D/decisions.json $D/updates --authorization "« instruction exacte de Jonathan »" --verify $D/verify.json
python -X utf8 scripts/research.py simulate $D/updates
for f in $D/updates/*.json; do python -X utf8 -B scripts/gtm.py record-update "$f" || echo "REFUS $f"; done
```

Ne lancer la boucle réelle que si `simulate` n'a aucun refus. Ensuite :

```powershell
.\scripts\crm.ps1 -Action sync
```

```bash
for i in 1 2 3; do python -X utf8 scripts/backup_local.py --configured && break; sleep 5; done
```

La sauvegarde peut échouer une fois parce que le superviseur CRM écrit pendant la copie :
réessayer, ne rien nettoyer à la main.

## 5. Nouveaux prospects

Cible : boutiques Shopify en France, Suisse ou Belgique, logistique externalisée, environ
5 à 100 salariés. Sources, par ordre de preuve logistique :

- pages références des 3PL (Bigblue, Futurlog, Wing, e-Logik, Webship, Station
  Fulfillment…), textes alternatifs des logos ;
- avis Shopify d'applications logistiques :
  `python -X utf8 scripts/research.py reviews <app> $D/reviews-<app>.json`
  (`bigblue`, `byrd`, `wing`, `activeants-app` ; puis `shippingbo`, `sendcloud`, `boxtal`,
  `packlink-pro`, qui prouvent Shopify et plusieurs transporteurs mais pas un 3PL) ;
- Clay `search-companies` si des crédits restent.

Ensuite : `probe` sur `[["Marque", "source", ["marque.fr", "marque.com"]], …]` pour le
signal Shopify, puis `crawl` et `registry` pour le pays et la taille (écarter pays hors
cible, sociétés cessées, groupes trop gros, micro-structures sans volume), puis les
contacts par la section 2 ou 3. Décisions au format de `draft_additions` (voir
`scripts/research.py`), puis `draft-additions`, `simulate`, et `gtm.py record-add` pour
chaque fichier `add-*.json`. Toujours dédoublonner contre le journal (le script refuse un
nom déjà présent).

## 6. Rapport à Jonathan

Court, en français : nombre de fiches traitées, emails nominatifs retenus (avec la
preuve : SMTP ou publication), décideurs sans email vérifiable, alertes (à écarter, trop
gros, repris), crédits Clay restants ou épuisés, révision du journal, état de la
projection et de la sauvegarde. Aucun commit sans demande.
