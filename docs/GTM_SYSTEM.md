# Système GTM Vision PnL — deux dossiers, un flux

Ce fichier est identique dans les deux dépôts. Toute IA qui ouvre l'un des deux
dossiers le lit en premier, puis l'`AGENTS.md` du dossier courant, puis — si la
tâche le demande — l'autre dossier par son chemin absolu ci-dessous.

## Les deux dossiers

| | Moteur GTM — journal | CRM GTM — projection |
|---|---|---|
| Chemin | `C:\Users\jonat\.codex\.chatgpt-projects\g-p-6aac1789067c81919abd82be2a92d0d3\gtm-vision-pnl` | `C:\dev\gtm-crm` |
| Dépôt | `github.com/spykernv/gtm-vision-pnl` (privé) | `github.com/spykernv/gtm-crm` (privé, remote `origin`, branche `gtm/pruned`) ; fork de `trycompai/crm` conservé en remote `upstream` — ne jamais y pousser |
| Rôle | Registre des **effets externes** : intentions d'envoi, reçus Gmail, preuves Calendly, compteurs de réponses, arrêts | Registre des **prospects** : entreprises, contacts, faits sourcés, pipeline, vues, reporting |
| Source de vérité | `local/GTM_Design_Partners_Etat.json` (hors Git) | Postgres `gtm_crm` — conteneur Docker `gtm-crm-postgres`, port **5433** |
| Moteur | `scripts/gtm.py` (Python, bibliothèque standard seule) | API NestJS `:3001` (OpenAPI sur `/openapi.json`) + app Next.js `:3000` |
| Exécution agentique | Orchestrateur Desktop, réveil horaire, protocole `ingest → prepare → arm → Gmail → receipt` (réponses) et `outbound-arm → Gmail → outbound-receipt` (envois) | **Aucune.** L'agent embarqué d'origine (eve, Perplexity, context.dev, Slack, tracking, télémétrie) a été retiré le 21/09/2026. Le CRM ne décide de rien et n'appelle aucun service externe. |
| Instructions IA | `AGENTS.md` (`CLAUDE.md` = `@AGENTS.md`) | `AGENTS.md` (`CLAUDE.md` = `@AGENTS.md`) |
| Données privées | `local/` — jamais dans Git | la base Postgres et `.env` — jamais dans Git |

## Règle d'or

**Le CRM ne conditionne jamais un envoi.** L'intention d'envoi est écrite sur disque
par le moteur avant l'appel Gmail ; c'est cette propriété qui empêche tout double
envoi, et elle ne dépend d'aucun appel réseau. Le flux va du journal **vers** le CRM,
jamais l'inverse pour quoi que ce soit qui gouverne un envoi ou une réponse. Si le
CRM est éteint, le moteur envoie, répond et journalise exactement comme avant.

## Correspondance des données

| Journal (JSON) | CRM (Postgres) | Clé de jointure |
|---|---|---|
| `sent[]` — un envoi initial | `Deal` + `Contact` + `Company` | `sent.result.thread_id` ↔ `EmailThread.rootMessageId` / `EmailMessage.gmailMessageId` ; `sent.to` ↔ `Contact.email` ; `sent.company` ↔ `Company.name` ; `sent.rank` |
| `sent[].conversation_state` | `Deal.stage` (`DealStage`) | mêmes sept valeurs : `WAITING_REPLY`, `QUALIFYING`, `PENDING_BOOKING`, `HANDOFF`, `BOOKED`, `STOPPED`, `BOUNCED` |
| `records[]` — les 50 candidats | `Company` + `FieldValue` sur des `FieldDefinition` `agentFilled` | `Entreprise` ↔ `Company.name` ; `Rang` |
| preuves sourcées (Shopify, 3PL, URL, date, confiance) | `CompanyFact` / `ContactFact` — `band`, `sourceUrl`, `evidence`, `status PROPOSED → APPLIED`, `decidedBy` | `field` + `companyId` / `contactId` |
| estimé / confirmé / inconnu | `band` = `POSSIBLE` / `PROBABLE` / `VERIFIED` ; inconnu = **pas de ligne** | jamais de points inventés |
| `STOPPED` / `BOUNCED` | `SuppressedContact` / `SuppressedDomain` | e-mail / domaine |
| `local_runtime.events` — entrants | `EmailMessage` (`direction INBOUND`) | `inbound_rfc_id` ↔ `rfcMessageId` |
| `booking_evidence` | `CalendarEvent` + `CalendarAttendee` | e-mail de l'invité |

## Boucle de travail — Jonathan répond à la main (depuis le 21/09/2026)

Jonathan rédige lui-même les réponses aux prospects. Claude lit la boîte, journalise
ce qui arrive, puis projette. Le CRM est un miroir : on ne l'édite jamais à la main,
il est reconstruit à chaque passage depuis le journal.

```
Gmail  ──ingest──▶  journal (vérité)  ──project-from-journal──▶  CRM (miroir)
```

À chaque point de contrôle :

1. lire les fils journalisés et la recherche de rebonds (connecteur Gmail) ;
2. `gtm.py ingest` chaque nouvel entrant — déduplication, preuves, machine à états ;
3. `bun packages/db/scripts/project-from-journal.ts` depuis `C:\dev\gtm-crm`
   (`--dry-run` pour ne rien écrire, `--journal PATH` pour un autre journal).

La projection est idempotente : elle recrée entreprises, contacts, deals, fils et
messages à partir du journal, et ne lit jamais le CRM pour en déduire quoi que ce soit.
Le champ entreprise **« Réponse reçue »** (Aucune / Accusé automatique / Réponse humaine /
Refus / Rebond) donne l'état de réponse en un coup d'œil ; `Deal.stage` porte l'état
de conversation du journal.

Limite connue : le journal enregistre les envois **du moteur**, pas les réponses
manuelles de Jonathan. Tant qu'aucune transition dédiée n'existe, une réponse manuelle
n'apparaît dans le journal qu'au prochain entrant sur le fil — `inspect_thread` détecte
alors le message humain et force HANDOFF.

## État au 21 septembre 2026

- Moteur : mode `live`, 25 envois journalisés, 0 réponse humaine, tâche horaire
  installée (dernier réveil observé 08:50 UTC).
- CRM : élagué et migré (33 tables, 57 migrations). Projection câblée le 21/09 :
  51 entreprises, 26 contacts, 26 deals, 26 fils, 30 messages (révision 59 du journal).
- Réponses : 1 humaine (test, HANDOFF), 3 accusés automatiques, 22 silences, 0 rebond.
- Non fait, dans cet ordre : (1) transition pour journaliser une réponse manuelle ;
  (2) serveur MCP devant l'API du CRM ; (3) réveil planifié sous Claude Code ;
  (4) projection des faits sourcés vers `CompanyFact`.

## Commandes

Moteur (depuis `gtm-vision-pnl`) :

```powershell
python -X utf8 scripts/gtm.py status
python -X utf8 scripts/gtm.py recover
python -X utf8 scripts/gtm.py scan-scope
python -X utf8 -B -m unittest discover -s tests
```

CRM (depuis `gtm-crm`) :

```powershell
docker compose up -d                      # Postgres isolé sur 5433
bun run dev                               # app :3000, API :3001
cd apps/api; bun test --env-file ../../.env --preload ./test/setup.ts
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5433/gtm_crm"; $env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/gtm_crm_test"; bun run db:test
```

Le script `test` du CRM ne charge pas le `.env` racine : passer `--env-file`.
`db:test` lit `DATABASE_URL` et `TEST_DATABASE_URL` dans l'environnement du shell.

## À ne pas confondre

`C:\dev\CRM` est le CRM de **networking personnel** de Jonathan : même logiciel
d'origine, base `crm-postgres` sur le port 5432, branche `feat/session-engine`.
Il est **hors périmètre GTM**. Ne pas y travailler pour le GTM, et ne jamais lancer
le `docker compose` de `gtm-crm` sans avoir vérifié que conteneur, volume et port
diffèrent — ils diffèrent aujourd'hui, c'est ce qui protège cette base.
