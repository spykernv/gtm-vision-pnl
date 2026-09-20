# Revue des chemins de reprise — 20 septembre 2026

Cette correction traite trois défauts reproduits après la première revue. Les tests
utilisent exclusivement des données synthétiques et des installations temporaires.

| Cas | Comportement corrigé | Vérification |
|---|---|---|
| Curseur expiré | `scan-restart` archive le scan incomplet, conserve ses IDs et sa requête, ouvre un nouvel identifiant ; aucun avancement du dernier scan complet avant une vraie dernière page | Reprise après redémarrage, curseur périmé concurrent, identifiant réutilisé, anciennes pages, panne disque |
| Rendez-vous remplacé | Remplacement refusé sans preuve d'annulation du précédent événement et de son invité ; anciennes preuves conservées dans `booking_history` | Annulation valide/invalide, autre invité/type/URI, doublon, arrêt métier, panne disque |
| Événement SAVED oublié | Restauration refusée avant écriture si elle perd ou modifie un événement déjà sauvegardé, y compris automatic/not_now | Journal intact au byte près, déduplication maintenue, restauration d'un snapshot compatible |

Les preuves de rendez-vous sont également protégées contre une restauration plus
ancienne, même si les deux snapshots portent BOOKED. Les scans et leurs historiques
actuels sont conservés lors d'une restauration.

Deux observations annexes sont traitées :

- `prepare` et `arm` contrôlent `fingerprint_version`. Les événements anciens encore
  en attente nécessitent une nouvelle lecture puis `reclassify`. Les SAVED restent
  inchangés ; aucune empreinte historique n'est recalculée à partir d'une vieille capture.
- `scan-scope` dérive les fils et les requêtes des envois admissibles du compte courant.
  La date de recherche est la veille du plus ancien envoi admissible, pour couvrir les
  limites de fuseau. Date manquante : blocage explicite. Périmètre vide : aucune requête.

Validation : les 13 premiers tests ajoutés échouaient sur le code antérieur (5 échecs
et 8 erreurs pour les fonctions absentes). Après correction et ajout de cinq cas
limites, les 54 tests passent : 36 existants et 18 nouveaux. Un essai supplémentaire
par l'interface de commandes vérifie la séquence scan-page, scan-restart et scan-page
finale dans une installation temporaire. Les preuves propres au poste restent hors Git.

Limites conservées explicitement :

- Une preuve de réponse Gmail finale doit venir du connecteur. Le moteur local ne peut
  pas authentifier cryptographiquement un JSON inventé par son appelant ; les procédures
  interdisent de fabriquer une page vide pour simuler une recherche complète.
- Un second rendez-vous actif peut être légitime. Sans preuve d'annulation du premier,
  le remplacement est bloqué pour vérification humaine ; le code n'annule et ne déplace
  aucun rendez-vous dans Calendly.
- Le hook Git doit être installé dans chaque clone selon le README. Git ne réplique
  pas automatiquement sa configuration locale.
- Une copie vérifiée dans un dossier OneDrive local ne prouve pas sa synchronisation
  distante. Les manifestes restent explicites sur cette distinction.
- Les tests synthétiques ne prouvent pas l'envoi d'une première réponse réelle avec
  reçu Gmail ; ce contrôle reste requis à la première occasion admissible.
