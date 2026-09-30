# Recherche de contacts sans fournisseur payant

Procédure mise en place le 29/09/2026, quand les crédits Clay étaient épuisés. Elle
remplace l'enrichissement payant par des sources publiques et une vérification technique.
Elle ne crée aucun envoi et n'écrit jamais le journal : les résultats passent ensuite par
`gtm.py record-update` ou `record-add` (voir RUNBOOK), puis par la projection vers le CRM.

L'opération complète se lance par le skill `.claude/skills/gtm-research` : **Clay en
premier réflexe**, puis cette procédure dès que Clay répond « Credits are exhausted ».
Le skill fixe aussi l'économie du forfait : scripts pour le travail mécanique, lecture
des seules sorties compactes, au plus 2 sous-agents en même temps sur de gros lots,
jamais l'outil Workflow.

## Règle de contact

1. Viser une personne physique responsable de la boutique : fondateur, dirigeant légal,
   puis opérations, logistique ou finance.
2. Une adresse nominative n'entre dans le journal que si :
   - la personne l'a publiée elle-même (site, profil public, annuaire professionnel) ;
   - ou `research.py verify` la marque `valide` : acceptée par le serveur de messagerie
     d'un domaine qui refuse les adresses inconnues.
3. Un domaine « accepte-tout » ne prouve rien. On garde le nom du décideur et une adresse
   de la boutique en repli, la plus pertinente pour l'offre (jamais le SAV si mieux existe).
4. Un résumé de moteur de recherche n'est pas une source : relire la page citée avant
   de retenir une adresse. Écarter une adresse sur un domaine étranger à la marque, sauf
   si le registre montre que ce domaine appartient à la société qui exploite la boutique.
5. Téléphone (demande du 30/09/2026) : chaque prospect reçoit, si elle existe, la ligne
   publiée par la boutique elle-même (lien `tel:`, page contact, mentions légales,
   Impressum), avec l'URL en provenance (colonnes `Téléphone` et `Téléphone : provenance`).
   `research.py phones` écarte les numéros d'hébergeur, de médiateur ou de place de marché.
   Pas de numéro tiré d'un annuaire ou d'un agrégateur ; un numéro personnel n'est retenu
   que si la personne l'a publié pour son activité. Aucun numéro publié : colonne vide.

## Outils (`scripts/research.py`)

Les fichiers de travail vont dans `local/research/AAAA-MM-JJ/` (hors Git). Chaque
sous-commande imprime une vue compacte ; c'est elle qu'on lit, pas le JSON.

| Sous-commande | Rôle |
|---|---|
| `targets OUT` | fiches à enrichir, lues dans le journal (fiches « À écarter » exclues) |
| `crawl TARGETS OUT` | pages de la boutique : adresses publiées, personnes, SIREN / BCE / IDE |
| `registry CRAWL OUT [--names F]` | registres officiels : dirigeants, effectif, CA |
| `summarize CRAWL REGISTRY OUT` | une ligne par boutique |
| `candidates PEOPLE OUT` | variantes d'adresse par personne et domaine |
| `verify CANDIDATES OUT` | vérification SMTP sans envoi |
| `reviews APP OUT [--pages N]` | marchands FR/CH/BE ayant noté une application Shopify |
| `probe CANDIDATES OUT` | signal Shopify, devise et titre de domaines candidats |
| `phones SHOPS OUT` | téléphone publié par chaque boutique et page source (lent : limite 429 de Shopify) |
| `draft-updates DECISIONS DIR --authorization … [--verify F…]` | entrées `record-update` |
| `draft-additions PROSPECTS DIR --authorization …` | entrées `record-add` |
| `simulate DIR` | rejoue les entrées sur une copie du journal |

`draft-updates` refuse une adresse marquée `smtp` absente des résultats `verify` fournis.
Sur une fiche déjà contactée, il n'écrit que les colonnes décideur. Le déroulé complet et
les formats de fichiers sont dans le skill `gtm-research`.

- `targets` retient les fiches sans email nominatif et les boutiques contactées sur une
  boîte partagée sans décideur.
- `crawl` lit le sitemap et les pages légales, « à propos », équipe et blog : adresses
  publiées, personnes citées avec un rôle, SIREN, BCE ou IDE suisse.
- `registry` interroge les registres officiels à partir de ces numéros :
  - France : `recherche-entreprises.api.gouv.fr` (dirigeants, holdings remontées d'un
    niveau, tranche d'effectif, chiffre d'affaires publié) ;
  - Belgique : BCE (`kbopub.economie.fgov.be`), fonctions et représentants permanents ;
  - Suisse : Zefix donne le lien de l'extrait cantonal ; les personnes (direction,
    signature) s'y lisent dans un navigateur.
  `names.json` donne une raison sociale ou un SIREN quand le site n'en affiche pas.
  Vérifier qu'un résultat par nom est bien la bonne société (homonymes fréquents).
- `people.json` : `{"rank": {"domains": ["domaine mail"], "people": ["Prénom Nom"]}}`.
  Le domaine mail peut différer du site (relever celui des adresses publiées).
- `verify` ouvre une session SMTP par lot : EHLO avec le nom DNS inverse de la
  connexion, `MAIL FROM:<>`, une adresse bidon pour détecter un domaine accepte-tout,
  puis les variantes, et `QUIT`. Aucune commande `DATA` : rien n'est envoyé. Il s'arrête
  dès qu'une variante d'une personne est acceptée.

## Limites connues

- Certains serveurs refusent une connexion depuis une adresse IP résidentielle (IONOS,
  Zoho) ou coupent la session après une vingtaine de tests (Microsoft 365, iCloud) : le
  résultat est alors `inconnu`, jamais une preuve.
- Des équipes utilisent un autre domaine que la boutique (par exemple le domaine du pays
  ou du groupe) : tester les domaines trouvés dans les adresses publiées.
- Rester à quelques dizaines de vérifications par domaine et par jour.
