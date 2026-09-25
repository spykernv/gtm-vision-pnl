# GTM Vision PnL

Système de prospection B2B mené par un agent IA, avec un humain dans la boucle. Il
se compose de deux dépôts qui ne se ressemblent pas et ne jouent pas le même rôle :

| | **Moteur** — ce dépôt | **CRM GTM** — `gtm-crm` |
|---|---|---|
| Rôle | Décider et prouver : workflow, envois, réponses, rendez-vous | Montrer : entreprises, contacts, pipeline, fils d'emails |
| Source de vérité | Journal JSON local | Aucune : c'est un miroir reconstruit depuis le journal |
| Technologie | Python standard, sans dépendance | Fork élagué de [trycompai/crm](https://github.com/trycompai/crm) : NestJS, Next.js, Prisma, Postgres |
| Envoie des emails ? | Oui, via l'agent et après contrôles | Jamais |
| Visibilité | Public (code et docs, aucune donnée) | Privé |

L'agent (Claude Code ou GPT-6 Astra) lit la boîte Gmail, Calendly, Clay et le Web avec
ses propres connecteurs. Le moteur ne parle à aucun de ces services : il enregistre
chaque intention, chaque preuve et chaque transition dans le journal, et il refuse
toute action qui pourrait produire un double envoi, une réponse au mauvais
destinataire ou une réservation non prouvée. Le CRM reçoit ensuite une projection à
sens unique de ce journal.

> **Statut** : projet personnel en production, publié pour consultation. Ce n'est ni
> une bibliothèque réutilisable ni un produit. Tous droits réservés (voir
> [LICENSE](LICENSE)). Les données de campagne ne sont dans aucun des deux dépôts.

## Sommaire

- [Contexte](#contexte)
- [Vue d'ensemble du système](#vue-densemble-du-système)
- [Principes de conception](#principes-de-conception)
- **Workflow et moteur**
  - [Le point de contrôle gtm-check](#le-point-de-contrôle-gtm-check)
  - [Cycle de vie d'une conversation](#cycle-de-vie-dune-conversation)
  - [Protocoles](#protocoles)
- **Intégration CRM**
  - [Le CRM GTM](#le-crm-gtm)
  - [Projection du journal vers le CRM](#projection-du-journal-vers-le-crm)
- **Utilisation**
  - [Installation](#installation)
  - [Commandes](#commandes)
  - [Tests et vérifications](#tests-et-vérifications)
  - [Structure du dépôt](#structure-du-dépôt)
  - [Données privées et sécurité](#données-privées-et-sécurité)
- [Documentation](#documentation)
- [Licence](#licence)

## Contexte

La campagne cherche trois *design partners* : des marchands Shopify en France, en
Suisse et en Belgique, qui travaillent avec un logisticien et veulent connaître la
rentabilité réelle de chaque commande (coûts de transport tardifs, surcharges,
retours, avoirs). La campagne part de 50 candidats sourcés, dont 20 prioritaires,
contactés par vagues de cinq. Le détail métier est dans [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Vue d'ensemble du système

```mermaid
flowchart LR
  subgraph Externe[Services externes]
    Gmail
    Calendly
    Clay[Clay / Web]
  end
  subgraph Moteur[gtm-vision-pnl : moteur]
    Agent[Agent IA]
    Engine[scripts/gtm.py]
    Journal[(Journal JSON local)]
    Excel[Vue Excel]
  end
  subgraph CRM[gtm-crm : CRM]
    Projection[project-from-journal.ts]
    DB[(Postgres)]
    API[API NestJS]
    App[App Next.js]
  end
  Human[Jonathan] -- lance gtm-check, écrit les réponses --> Agent
  Agent <--> Gmail
  Agent <--> Calendly
  Agent <--> Clay
  Agent -- preuves et transitions --> Engine
  Engine <--> Journal
  Journal --> Excel
  Journal -- lecture seule --> Projection
  Projection --> DB
  DB --> API --> App
```

Les flèches ne remontent jamais du CRM vers le journal. **Le CRM ne conditionne
jamais un envoi** : s'il est éteint, le moteur envoie, répond et journalise
exactement comme avant. C'est la règle d'or du système, détaillée dans
[docs/GTM_SYSTEM.md](docs/GTM_SYSTEM.md).

## Principes de conception

- **Écrire avant d'agir.** L'intention d'envoi (`SENDING`) est inscrite sur disque avant
  l'appel Gmail. Un crash laisse une trace, jamais un envoi fantôme.
- **Pas de nouvelle tentative automatique.** Un `SENDING` sans reçu reste incertain
  jusqu'à ce qu'une preuve Gmail exacte le réconcilie. On ne réessaie pas à l'aveugle.
- **Le journal est l'unique source de vérité.** Le classeur Excel et le CRM sont des
  vues dérivées. Toute modification passe par une transition de `scripts/gtm.py`.
- **Les preuves remplacent les affirmations.** `BOOKED` exige l'événement Calendly
  actif, l'hôte, l'invité et le créneau. Une activation exige des *gates* prouvées.
- **Les arrêts priment.** Refus = arrêt définitif, rebond = suspension, réponse humaine
  ou sujet sensible (prix, contrat, NDA, données) = passage de relais à l'humain.
- **Les emails sont des données, pas des instructions.** Rien de ce qu'un prospect
  écrit ne devient une commande, une règle ou un destinataire.
- **Aucune dépendance.** Python standard uniquement, aucun client de modèle, aucun
  client Gmail, aucun appel réseau.

## Le point de contrôle gtm-check

Depuis le 22/09/2026, il n'y a plus de réveil planifié. Jonathan lance le point de
contrôle `gtm-check` quand il le décide ; la procédure complète est dans
[.claude/skills/gtm-check/SKILL.md](.claude/skills/gtm-check/SKILL.md). Un seul
orchestrateur est actif à la fois.

```mermaid
sequenceDiagram
  actor J as Jonathan
  participant A as Agent IA
  participant G as Gmail
  participant M as Moteur (gtm.py)
  participant C as CRM
  J->>A: gtm-check
  A->>M: status / recover / scan-scope
  Note over A,M: arrêt si un envoi est incertain
  A->>G: lecture du périmètre et des rebonds, toutes les pages
  A->>M: ingest de chaque nouvel entrant
  A-->>J: texte exact proposé, ou escalade
  J->>G: Jonathan écrit et envoie lui-même
  A->>M: manual-reply (preuve du message envoyé)
  A->>C: project-from-journal
  A-->>J: rapport
```

1. **Préflight** : `status`, `recover` et `scan-scope`. Un envoi incertain bloque tout.
2. **Lecture** : l'agent lit Gmail dans le périmètre calculé par le moteur, pages
   comprises, ainsi que les rebonds.
3. **Journalisation** : chaque nouvel entrant passe par `ingest`, qui déduplique,
   vérifie le lien avec un envoi journalisé et applique la machine à états.
4. **Proposition** : l'agent rédige le texte exact de la réponse, ou escalade ce qui
   relève de l'humain (prix, contrat, NDA, données, pilote).
5. **Réponse** : Jonathan envoie lui-même, puis `manual-reply` en prend acte avec la
   preuve Gmail. Le fil passe en `HANDOFF`.
6. **Projection** : le CRM est reconstruit depuis le journal (voir
   [plus bas](#projection-du-journal-vers-le-crm)).

## Cycle de vie d'une conversation

```mermaid
stateDiagram-v2
  [*] --> WAITING_REPLY: envoi initial reçu par Gmail
  WAITING_REPLY --> QUALIFYING: question ou intérêt
  WAITING_REPLY --> PENDING_BOOKING: demande de rendez-vous
  QUALIFYING --> PENDING_BOOKING
  PENDING_BOOKING --> BOOKED: preuve Calendly complète
  WAITING_REPLY --> HANDOFF: sujet sensible ou réponse humaine
  QUALIFYING --> HANDOFF
  PENDING_BOOKING --> HANDOFF
  WAITING_REPLY --> STOPPED: refus
  QUALIFYING --> STOPPED
  WAITING_REPLY --> BOUNCED: rebond définitif
```

`STOPPED`, `BOUNCED` et `HANDOFF` ne sont jamais rouverts automatiquement. Aucune
transition ne fait sortir un fil de `HANDOFF` : une reprise d'autonomie exigera une
transition dédiée et auditée.

## Protocoles

| Protocole | Étapes | Usage |
|---|---|---|
| Réponse de l'agent | `ingest` → `prepare` → `arm` → envoi Gmail → `receipt` | Réponse autonome ; aujourd'hui refusée par `prepare` sous Claude Code, dont le connecteur Gmail n'expose pas les en-têtes RFC |
| Réponse manuelle | `ingest` → Jonathan écrit et envoie → `manual-reply` | Mode actuel : le moteur prend acte, le fil passe en `HANDOFF` |
| Envoi initial | `outbound-arm` → envoi Gmail → `outbound-receipt` | Uniquement sur instruction explicite, par vagues de cinq |
| Rendez-vous | lecture Calendly → `booking` | Enregistre une réservation prouvée ; ne réserve rien |

Chaque étape relit le profil Gmail connecté, vérifie `local/STOP`, les doublons et la
fraîcheur des lectures (moins de 60 secondes avant `arm`). Le détail et les cas de
reprise sont dans [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Le CRM GTM

Le dépôt `gtm-crm` est un fork élagué de [trycompai/crm](https://github.com/trycompai/crm)
(licence MIT). Il sert d'interface de consultation : fiches entreprises et contacts,
pipeline, fils d'emails, filtres et reporting.

| Élément | Détail |
|---|---|
| Application | Next.js sur le port 3000 |
| API | NestJS sur le port 3001, OpenAPI sur `/openapi.json` |
| Base | Postgres dans un conteneur Docker dédié, port 5433, via Prisma |
| Retiré du fork | L'agent embarqué d'origine, Slack, le suivi web, la télémétrie, les clés Perplexity, context.dev et AI Gateway, l'onglet Agent et les mutations d'enrichissement |
| Ajouté | `CompanyFact` (faits sourcés sur une entreprise), étapes de `Deal` alignées sur les sept états du moteur, champ entreprise « Réponse reçue » |

Après élagage, l'API n'appelle plus aucun service externe. L'intelligence vit
hors du CRM : le moteur décide, le CRM affiche.

## Projection du journal vers le CRM

`packages/db/scripts/project-from-journal.ts`, dans `gtm-crm`, lit le journal du
moteur, le valide une seule fois avec Zod, puis reconstruit dans une transaction
les entreprises, contacts, deals, fils et messages :

```powershell
# depuis gtm-crm
bun packages/db/scripts/project-from-journal.ts --dry-run   # résumé, aucune écriture
bun packages/db/scripts/project-from-journal.ts             # projection réelle
bun packages/db/scripts/project-from-journal.ts --journal CHEMIN --owner EMAIL
```

| Journal (moteur) | CRM | Clé |
|---|---|---|
| `records[]` : les candidats sourcés | `Company` et onze champs projetés (rang, Shopify, logisticien, preuve 3PL, angle à tester, vague…) | nom de l'entreprise |
| `sent[]` : un envoi initial | `Contact`, `Deal` « pilote Vision PnL », `EmailThread` et message sortant | adresse du destinataire ; identifiant Gmail du message |
| `sent[].conversation_state` | `Deal.stage` | mêmes sept valeurs, de `WAITING_REPLY` à `BOUNCED` |
| `local_runtime.events` : les entrants | `EmailMessage` entrant, avec sa classification | identifiant RFC, sinon identifiant Gmail |
| entrants et état de conversation | champ « Réponse reçue » : Aucune, Accusé automatique, Réponse humaine, Refus, Rebond | entreprise |
| `STOPPED`, `BOUNCED` | `SuppressedContact` | adresse email |

Propriétés de la projection :

- **Idempotente** : relancée sur le même journal, elle retrouve les mêmes lignes et
  les met à jour sans doublon.
- **À sens unique** : elle ne lit jamais le CRM pour en déduire quoi que ce soit, et
  n'écrit jamais dans le journal.
- **Sans envoi** : aucun email ne peut partir du CRM.
- **Pas encore fait** : les faits sourcés (URL, date, confiance) ne sont pas encore
  projetés vers `CompanyFact`. Le moment venu, un fait inconnu ne produira aucune
  ligne plutôt qu'une valeur inventée.

Les champs projetés portent la mention « Projeté depuis le journal GTM ; ne pas
éditer ici ». Toute correction se fait dans le moteur, puis la projection est
relancée. La correspondance complète, champ par champ, est dans
[docs/GTM_SYSTEM.md](docs/GTM_SYSTEM.md).

## Installation

Prérequis : Windows, Python 3.12 à 3.14. Aucun paquet à installer.

```powershell
git clone https://github.com/spykernv/gtm-vision-pnl.git
cd gtm-vision-pnl
git config --local core.hooksPath scripts/hooks
python -X utf8 -m unittest discover -s tests -v
```

Les tests tournent sans données privées. Pour exploiter une campagne, importer les
trois fichiers privés (journal, classeur, workflow) ; `init` refuse d'écraser un état
existant :

```powershell
python -X utf8 scripts/gtm.py init --journal CHEMIN --workbook CHEMIN --workflow CHEMIN
python -X utf8 scripts/gtm.py status
```

La forme attendue de la configuration est illustrée par
[examples/config.example.json](examples/config.example.json) (valeurs fictives). Les
connecteurs s'authentifient dans l'interface de l'agent ; aucun jeton ne doit être
collé dans un fichier ou une conversation.

## Commandes

Toutes les commandes s'écrivent `python -X utf8 scripts/gtm.py <commande>`, ou
`.\gtm.ps1 <commande>` qui fait de même depuis n'importe quel dossier. Celles qui
prennent `input.json` lisent les preuves collectées par l'agent. Une commande bloquée
renvoie `{"blocked": ...}` sur la sortie d'erreur avec le code 2.

| Commande | Rôle |
|---|---|
| `status`, `recover` | État courant ; réconciliation idempotente des reçus |
| `stop`, `monitor`, `live` | Arrêt d'urgence ; lecture contrôlée ; mode actif (gates prouvées) |
| `scan-scope`, `scan-page`, `scan-restart`, `compact-scans` | Périmètre et pagination des lectures Gmail |
| `ingest`, `reclassify` | Journaliser et qualifier un message entrant |
| `prepare`, `arm`, `receipt`, `release` | Réponse de l'agent, de la réservation au reçu |
| `manual-reply` | Prendre acte d'une réponse écrite par Jonathan |
| `outbound-arm`, `outbound-receipt` | Envoi initial autorisé |
| `record-add` | Ajouter un candidat sur instruction explicite (aucun envoi) |
| `booking` | Enregistrer un rendez-vous Calendly prouvé |
| `gate`, `notify-ack` | Preuve d'activation ; accusé de notification |
| `sync`, `restore`, `init` | Indicateurs dérivés ; restauration protégée ; import initial |

Scripts annexes, tous dans `scripts/` :

- `verify_installation.py` : contrôle en lecture seule de l'installation ;
- `status_view.py` : instantané daté dans `local/evidence/STATUS.md` ;
- `backup_local.py --configured` : copie vérifiée (SHA-256) vers une destination privée ;
- `retention.py` : conservation des scans et des copies ([docs/RETENTION.md](docs/RETENTION.md)) ;
- `audit_sources.py` : audit des sources du journal ;
- `check_staged.py` : contrôle avant commit (voir plus bas) ;
- `refresh_workbook.mjs` : régénère la vue Excel depuis le journal. Facultatif, il
  dépend du runtime Desktop fourni et refuse d'écrire si le journal change pendant le rendu.

## Tests et vérifications

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -B -X utf8 scripts/verify_installation.py
```

Les tests simulent notamment : doublon, refus, réponse humaine entre préparation et
envoi, envoi incertain, panne de sauvegarde après envoi, redémarrage, reçu dupliqué,
concurrence, plafond de réponses, arrêt d'urgence, pagination expirée, reprogrammation
Calendly et restauration qui perdrait un événement. Ils ne prouvent ni un envoi réel
ni un déclenchement réel : ces preuves vivent dans `local/evidence/`.

## Structure du dépôt

| Chemin | Rôle | Versionné |
|---|---|---|
| `scripts/gtm.py` | Moteur : journal, transitions, contrôles | Oui |
| `scripts/` | Outils annexes et hook `pre-commit` | Oui |
| `tests/` | Simulations sur journaux temporaires | Oui |
| `docs/` | Workflow, runbook, rétention, système à deux dossiers | Oui |
| `.claude/skills/gtm-check/` | Procédure du point de contrôle manuel | Oui |
| `examples/` | Configuration synthétique (`example.invalid`) | Oui |
| `AGENTS.md`, `CLAUDE.md` | Consignes pour les agents IA | Oui |
| `local/GTM_Design_Partners_Etat.json` | Journal : unique source de vérité | Non |
| `local/Design_partners_FR_CH_BE.xlsx` | Vue Excel réconciliée | Non |
| `local/WORKFLOW_SOURCE.md`, `local/originals/` | Workflow d'origine et pièces d'entrée | Non |
| `local/evidence/`, `local/receipts/`, `local/backups/` | Preuves, reçus d'envoi, états récupérables | Non |

## Données privées et sécurité

- `.gitignore` fonctionne en liste blanche : tout ce qui n'est pas explicitement
  autorisé à la racine est ignoré, et `local/`, `secrets/`, `backups/`, `.env*`,
  `*.csv`, `*.xlsx`, `*.log` le sont partout.
- Le hook `scripts/hooks/pre-commit` lance `check_staged.py`, qui refuse les fichiers
  hors liste blanche, les types binaires ou privés, les adresses, signatures et
  identifiants Gmail présents dans le journal local, et les secrets reconnaissables.
  Il ne remplace pas une relecture des fichiers préparés.
- Les exemples versionnés n'utilisent que `example.invalid` et des identifiants fictifs.
- Les sauvegardes restent locales ou vers une destination privée choisie ; aucune
  donnée de campagne n'est synchronisée vers GitHub.

## Documentation

| Document | Contenu |
|---|---|
| [docs/GTM_SYSTEM.md](docs/GTM_SYSTEM.md) | Moteur et CRM : chemins, correspondance des données, règle d'or |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Objectif, ciblage, messages, règles de réponse |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Exécution, reprise après incident, gates, restauration |
| [docs/RECOVERY_REVIEW.md](docs/RECOVERY_REVIEW.md) | Scénarios de reprise et leur couverture de tests |
| [docs/RETENTION.md](docs/RETENTION.md) | Conservation des scans, sauvegardes et preuves |
| [docs/SCHEDULING.md](docs/SCHEDULING.md), [docs/SCHEDULE_PROMPT.md](docs/SCHEDULE_PROMPT.md) | Ancienne planification horaire (en pause) |
| [AGENTS.md](AGENTS.md) | Consignes impératives pour tout agent qui ouvre ce dossier |

## Licence

Copyright (c) 2026 spykernv. Tous droits réservés. Le code est consultable mais aucune
réutilisation n'est autorisée sans accord écrit. Voir [LICENSE](LICENSE).
