# GTM Vision PnL local

Installation locale pour un seul orchestrateur Desktop utilisant les plugins Gmail,
Clay, Web et Calendly. Le code assure journal, contrôles, sauvegardes et reprise.
Il ne contient ni client de modèle ni client Gmail autonome. Les réponses automatiques
ne sont pas actives tant que les gates ne sont pas prouvées.

## Ouvrir et reprendre

Dans Desktop, ajouter un projet local en choisissant **ce dossier gtm-vision-pnl**,
puis ouvrir une tâche locale dans ce projet. Choisir **GPT-6 Astra** dans le sélecteur.
Le miroir parent ChatGPT et `sources/` restent des références non modifiées. Ne pas
travailler dans un nouveau worktree sans les données locales : elles sont hors Git.

Demande de reprise : « Lis AGENTS.md, vérifie le statut local et reprends la migration
sans nouvel envoi de campagne. » Le modèle n'est jamais sélectionné par un fichier.

## Commandes

Depuis ce dossier, Python 3.12–3.14, aucune dépendance Python externe :

```powershell
python -X utf8 scripts/gtm.py status
python -X utf8 -m unittest discover -s tests -v
python -X utf8 scripts/gtm.py stop
python -X utf8 scripts/gtm.py recover
python -X utf8 scripts/gtm.py scan-scope
python -X utf8 scripts/gtm.py monitor
python -B -X utf8 scripts/verify_installation.py
```

`stop` est l'arrêt d'urgence. Mettre aussi la tâche Scheduled en pause pour arrêter
les réveils. `monitor` reprend la lecture contrôlée ; il ne lance pas de processus.
`live` n'est accepté que lorsque tous les prérequis sont prouvés. La première activation
et les interfaces de fichiers sont décrites dans [le runbook](docs/RUNBOOK.md).

## Fichiers

| Chemin | Rôle | Git |
|---|---|---|
| local/GTM_Design_Partners_Etat.json | Unique référence, historique et état technique local | Non |
| local/Design_partners_FR_CH_BE.xlsx | Vue Excel réconciliée | Non |
| local/WORKFLOW_SOURCE.md | Workflow original complet et messages validés | Non |
| local/originals/ | Copies exactes des trois pièces d'entrée | Non |
| local/evidence/ | Vérifications, audit et traces réelles | Non |
| local/backups/, local/receipts/ | États récupérables et preuves d'envoi | Non |
| scripts/, tests/ | Moteur local et simulations | Oui |
| docs/, examples/ | Procédures génériques et configuration synthétique | Oui |

Après un clone, réimporter les trois fichiers privés avec `scripts/gtm.py init
--journal CHEMIN --workbook CHEMIN --workflow CHEMIN`. Init refuse d'écraser un état
existant. Les secrets ne doivent jamais être collés dans une conversation ni committés.
Authentifier les plugins dans l'interface du compte ; leur OAuth n'est pas disponible
automatiquement dans Python ou GitHub Actions.

L'outil facultatif `scripts/refresh_workbook.mjs` utilise le runtime Desktop fourni
(@oai/artifact-tool 2.8.59, bundle 26.905.11957), sans téléchargement. Le cœur Python
fonctionne sans lui. Il dérive les notes de statut du journal, sans synchronisation
bidirectionnelle. Toute modification métier doit d'abord être enregistrée dans le JSON.
Passer `--automation-config CHEMIN_AUTOMATION_TOML` pour afficher le statut observé
de la tâche ; sinon il reste non vérifié. Chaque export conserve un avant/après daté.
La commande refuse de remplacer le classeur si le journal change pendant le rendu.

## Architecture installée

```mermaid
flowchart TD
  Desktop[Orchestrateur Desktop] <--> Plugins[Gmail / Clay / Web / Calendly]
  Desktop --> Python[Contrôles et transitions Python]
  Python <--> JSON[Journal JSON local]
  Python --> Recovery[Sauvegardes et reçus locaux]
  JSON --> Excel[Vue Excel]
  Timer[Réveil horaire — état dans Desktop] -.-> Desktop
  Repo[GitHub privé : code et docs] --- Python
```

Le PC, l'application et Internet sont nécessaires pour ce fonctionnement local.
L'ancienne tâche n'est pas modifiée pendant l'installation. Voir [planification et
coûts](docs/SCHEDULING.md) et [workflow métier](docs/WORKFLOW.md). Aucun workflow GitHub
Actions n'est installé : il ne fournit pas le déclenchement local Astra nécessaire.

## Vérifications

Tests en simulation : doublon, refus, réponse humaine entre préparation/envoi,
envoi incertain, panne de sauvegarde après envoi, redémarrage, réception dupliquée,
concurrence, plafond de réponses, arrêt d'urgence, pagination et réservation vérifiée.
Ces tests ne constituent pas une preuve d'envoi réel ni de déclenchement planifié.
Les scénarios de reprise couvrent aussi le curseur expiré (`scan-restart`), la
reprogrammation avec preuves d'annulation et la préservation des événements SAVED.
Les preuves initiales sont dans local/evidence/DELIVERY.md. L'état courant est un
instantané daté dans local/evidence/STATUS.md, généré par scripts/status_view.py.
Le vérificateur d'installation ne modifie ni journal, ni gates, ni rapports.

Installer le contrôle avant commit dans chaque clone :

```powershell
git config --local core.hooksPath scripts/hooks
python -B -X utf8 scripts/check_staged.py
```

Le hook refuse fichiers privés, contacts et secrets détectables. Il ne remplace pas
la revue des fichiers préparés. Les copies privées restent hors Git ; une destination
de sauvegarde choisie par l'utilisateur est prise en charge par scripts/backup_local.py.
