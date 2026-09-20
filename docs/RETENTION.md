# Conservation et récupération

Le contrôle horaire ne doit pas recopier indéfiniment des copies de copies. La
conservation porte sur les états techniques répétitifs, pas sur les preuves métier.

## Scans

Le journal conserve le scan courant et les 24 derniers scans. Les identifiants sont
attribués par un compteur monotone : `scan-scope` donne `next_scan_id`. Les commandes
`scan-page` et `scan-restart` exigent cet identifiant pour commencer une nouvelle
recherche et incrémentent le compteur dans la même transaction. Une page ancienne
reste refusée même si son scan n'est plus dans l'historique et si sa date est modifiée.
La pagination d'un scan courant conserve son ID et sa date de départ.

Les IDs détectés non encore journalisés sont reportés dans le scan courant. Les
événements ingérés, y compris ceux en attente, restent dans le registre d'événements.
Les anciens incidents abandonnés sont archivés avec leurs preuves dans scan-incidents
avant de quitter l'historique. Une panne d'archivage empêche la modification du journal.
Une archive créée juste avant une panne de commit peut rester présente : elle est
idempotente et ne valide aucun scan. Les anciennes captures restent des preuves datées.

## Sauvegardes

Chaque mutation garde une copie locale précédente. La copie externe contient le
journal courant, les reçus, originaux, fichiers de travail et preuves, mais exclut
`local/backups/`. Chaque instantané externe reste autonome : aucun lien matériel,
aucune dépendance à un autre instantané pour le récupérer.

Après une nouvelle copie vérifiée par SHA-256, et sous le verrou du journal, le
nettoyage conserve l'union des points suivants (les doublons ne comptent qu'une fois) :

| Type | Copies les plus récentes | Dernier point de chaque jour | Dernier point de chaque mois | Maximum ordinaire |
|---|---:|---:|---:|---:|
| Journaux locaux | 48 | 30 jours distincts | 12 mois distincts | 90 |
| Instantanés externes | 24 | 30 jours distincts | 12 mois distincts | 66 |

Il s'agit des dernières dates observées, même après une interruption prolongée, pas
d'une expiration aveugle au bout de 30 jours. Sans copie externe réussie, aucun
nettoyage local n'a lieu. Le journal continue alors à produire des copies locales ;
réparer la sauvegarde au lieu de supprimer ses preuves.

Exceptions conservatrices :

- CLAIMED ou SENDING suspend tout nettoyage jusqu'à réconciliation.
- Les anciennes copies externes sans marqueur de cette politique restent intactes.
- Les fichiers manuels, noms inconnus, autres installations et dossiers .partial ne
  sont jamais supprimés automatiquement.
- Un instantané externe contenant une preuve immuable absente ou différente dans la
  nouvelle copie reste conservé. Seuls le journal courant, STATUS.md et STOP sont
  considérés comme remplaçables ; la copie courante reste complète.
- Avant toute suppression d'un instantané, son manifeste et ses fichiers sont
  revérifiés. Une corruption, un lien, une jonction ou un chemin hors destination
  refuse le nettoyage. Une copie réussie avec nettoyage échoué retourne cleanup_error.

Ces exceptions peuvent dépasser les plafonds : elles privilégient la récupération.
Le volume des preuves métier, des reçus et des captures historiques peut toujours
croître. La politique borne le nombre de copies ordinaires et l'historique des scans,
pas toutes les données du projet. Elle supprime l'amplification due aux copies imbriquées.

## Récupération

Pour une erreur locale, utiliser restore selon RUNBOOK.md ; la commande préserve les
événements protégés, arrêts, reçus, réservations, scans et compteur courant. Pour la
perte du poste, copier le dossier local d'un instantané dans une installation isolée,
créer STOP, laisser la tâche en pause et réconcilier avec Gmail avant toute reprise.
Une ancienne copie ne prouve pas l'absence d'envoi après sa création.

La vérification des fichiers dans OneDrive local ne prouve ni leur synchronisation
cloud ni un test de perte physique du poste. Les simulations de restauration utilisent
des installations temporaires et n'envoient aucun message.
