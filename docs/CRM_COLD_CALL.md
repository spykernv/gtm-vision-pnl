# Préparation des appels

Sur demande de Jonathan du 29 septembre 2026, le dossier privé
`local/cold-call-20260929/` conserve les pages consultées, le plan d’enrichissement
et les reçus CRM. Le journal des envois reste inchangé.

Le plan sépare les numéros professionnels publiés des coordonnées restant à
confirmer. Une publication ne prouve ni la joignabilité ni une ligne directe du
décideur. Les numéros de prestataires et les canaux réservés à WhatsApp sont exclus
des tâches d’appel.

La projection dédiée `scripts/crm-cold-call.ps1 -PlanFile local/cold-call-20260929/plan.json`
affiche le périmètre préparé. Ajouter `-Apply` applique le plan autorisé à l’API locale
sous le compte propriétaire, après validation du journal courant.

Pour chaque numéro confirmé, elle complète le téléphone de l’entreprise, crée un
contact générique « Accueil professionnel » et une tâche « Cold call — Entreprise ».
La tâche contient les deux trames, la source, le type de ligne et la personne à
demander. Un numéro d’accueil n’est jamais attribué au contact nominatif du dirigeant.
Les autres entreprises ont une tâche « Cold call — trouver le numéro — Entreprise »
avec les prochaines étapes et les deux trames. Les notes de recherche restent
conservées comme preuves. Ce complément est enregistré dans
`local/cold-call-20260929/enrichment-tasks/plan.json`, avec ses propres reçus.
Il ne renseigne aucun téléphone tant qu’aucun numéro n’est confirmé.

Les activités se retrouvent dans la fiche entreprise ou contact, onglet **Activity**,
puis filtre **Upcoming** pour les tâches ouvertes. Il n’y a pas de page globale
« Tâches » dans l’interface actuelle. Le bloc **Overdue tasks** du tableau de bord
montre seulement les tâches à échéance dépassée ; il exclut les tâches sans date. Les
tâches sans date restent ouvertes sans inventer un rendez-vous ou une échéance.
La préparation n’enregistre aucun appel comme réalisé et ne déclenche aucun envoi.

Le script conserve l’état avant modification, écrit une intention avant création,
relit chaque résultat et déduplique par référence. Il conserve les tâches terminées.
Une création au résultat incertain doit être réconciliée avant nouvelle tentative.
Une coordonnée déjà présente et différente n’est pas écrasée.

Le superviseur CRM continue de projeter le journal ; il préserve ces téléphones,
contacts et activités supplémentaires. Il n’exécute pas ce script d’appel.
Un nouveau lot d’enrichissement demande un nouveau plan vérifié et une exécution
explicite. Aucun service payant ni recherche récurrente n’est ajouté.
