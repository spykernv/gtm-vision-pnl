# Accès local au CRM Vision P&L

Installation du 29 septembre 2026. CRM : `C:\dev\gtm-crm`. Le dossier
`C:\dev\CRM` reste hors périmètre.

## Accès pour Jonathan et les prochaines sessions

- Sur le Bureau : double-cliquer sur **Vision P&L CRM**. Le raccourci appelle
  `scripts/open-crm.ps1`, démarre les services si nécessaire, attend leur disponibilité
  (jusqu'à trois minutes au démarrage à froid), puis ouvre le navigateur habituel.
  Aucune fenêtre de terminal n'est nécessaire. Fermer le navigateur laisse le CRM actif.
- Interface : http://localhost:3000 (connexion Google habituelle).
- API : http://localhost:3001 ; documentation : http://localhost:3001/openapi.json.
- Les deux serveurs écoutent sur `127.0.0.1`. Aucun hébergement public ajouté.
- Point d'entrée de l'orchestrateur : `scripts/crm.ps1` dans le moteur GTM.
- La clé « GTM local orchestrator » appartient au compte propriétaire existant.
  Elle n'expire pas automatiquement. Elle reste révocable dans les paramètres API
  du CRM. Elle ne permet pas de gérer d'autres clés via l'API.
- La clé est chiffrée par Windows pour Jonathan, dans
  `local/crm-runtime/credential.xml`. Le dossier est privé, exclu de Git et réservé
  à Jonathan et SYSTEM. Ne jamais afficher son contenu, le joindre à un rapport,
  ni le copier dans un autre projet. Un autre compte Windows ne peut pas le déchiffrer.

Depuis le dossier du moteur, sous le compte Windows de Jonathan :

```powershell
.\scripts\crm.ps1 -Action status
.\scripts\crm.ps1 -Action start
.\scripts\crm.ps1 -Action sync
.\scripts\crm.ps1 -Action request -Path /rest/companies/search -Method POST
.\scripts\crm.ps1 -Action request -Path /rest/contacts/search -Method POST
.\scripts\crm.ps1 -Action request -Path /rest/companies/IDENTIFIANT -Method GET
```

`-BodyFile` accepte un fichier JSON de filtres pour une recherche. Les réponses
restent paginées : utiliser `page` et `pageSize` selon `/openapi.json`, jusqu'à `total`.
Les fiches entreprises et contacts exposent les faits, leurs sources et leur statut.
Le script limite les requêtes à l'API locale et aux lectures/recherches. Les mises à
jour GTM passent par le moteur, puis sa projection, jamais par un contournement du journal.

Dans une session Codex restreinte, exécuter ce point d'entrée avec les permissions
du compte propriétaire. Le bac à sable seul ne peut pas lire les secrets Windows.
La clé ne dépend pas du navigateur ou d'un onglet ouvert. Aucun connecteur MCP
supplémentaire n'est installé : l'accès vérifié est celui de l'API locale.

## Démarrage et maintien en fonctionnement

L'entrée Windows `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\VisionPnlCRM`
lance le superviseur, en fenêtre cachée, à l'ouverture de session. Le superviseur :

1. attend Docker Desktop et démarre le conteneur existant `gtm-crm-postgres` si nécessaire ;
2. lance l'API et l'interface, avec les dépendances déjà installées ;
3. relance un processus serveur qui s'arrête ;
4. vérifie toutes les 15 secondes si le journal ou ses preuves locales ont changé ;
5. projette les changements et conserve le dernier résultat dans `local/crm-runtime/last-sync.json`.

Un verrou empêche deux superviseurs simultanés. Les identifiants et dates de lancement
permettent d'arrêter uniquement les processus appartenant à ce CRM. Les journaux restent
locaux et tournent à 2 Mo. Ils ne partent pas dans la sauvegarde externe, pas plus que
`processes.json` et `last-*.json` (voir docs/RETENTION.md) ; `credential.xml` y reste. Une erreur de synchronisation n'altère pas le journal GTM ;
le superviseur conserve l'erreur et réessaie au passage suivant.

Ce service maintient le CRM et sa projection. Il ne lance aucun agent, aucun modèle,
aucune lecture Gmail/Calendly, aucune prospection et aucun envoi. `gtm-check` reste manuel.

Le PC doit être allumé, éveillé et la session Windows ouverte. Au redémarrage, la
relance se produit après connexion de Jonathan. Ce dispositif ne fournit pas un service
cloud disponible quand le PC est éteint.

```powershell
.\scripts\crm.ps1 -Action stop
.\scripts\crm.ps1 -Action start
```

`stop` conserve l'entrée de démarrage : le CRM redémarre à la prochaine ouverture
de session. Pour retirer le lancement automatique, supprimer uniquement l'entrée
Windows `VisionPnlCRM`, puis arrêter le superviseur. Ne pas arrêter les autres conteneurs.

## Contenu synchronisé et limites des preuves

- Les 51 entreprises, dont le test interne, et les contacts connus avant tout envoi.
- Les champs d'origine : contact public, profil, provenance de l'email, signal Shopify,
  sources logistiques, hypothèses et vérifications restantes.
- Les deals et les fils déjà journalisés ; les corps entrants retrouvés dans les
  preuves locales sont joints par identifiants Gmail/RFC exacts.
- Les réponses manuelles enregistrées par `gtm.py manual-reply`.
- Les réservations avec preuve Calendly valide, leurs participants et les annulations
  attestées lors d'un changement de réservation. Aucun BOOKED déduit d'un simple email.
- Les exclusions STOPPED/BOUNCED, sans effacement d'une exclusion existante.
- Une activité par fil et par rendez-vous. Réexécuter la projection ne crée pas de doublon.
- Le champ Périmètre distingue Prospection, Historique — suivi manuel, et Test interne.

Les cinq anciens fils ne font l'objet d'aucune nouvelle lecture ou surveillance.
Leur trace existante reste historique. Le test interne ne constitue pas un résultat commercial.

Les faits importés restent `PROPOSED`. Le niveau qualitatif vient des indications du
journal : Shopify confirmé, cas marchand probable, référence historique possible.
Une synchronisation ne revérifie pas une page Web. Le score numérique et la date
d'observation restent `null` lorsque la source ne les fournit pas. La migration du
29/09 autorise ces valeurs absentes sans inventer de score ou de date. Les profils
publics restent des propositions à vérifier, surtout si le nom diffère ou désigne une équipe.

La fraîcheur se lit dans `source_updated_at`, distinct de `projected_at`. Le journal
existant est daté du 21/09 ; le projeter le 29/09 n'est pas un nouveau relevé des réponses.
Pour actualiser Gmail ou les réservations, Jonathan lance le protocole GTM habituel.

## Vérification et maintenance

La sauvegarde préalable se trouve dans `local/crm-backups/pre-sync-20260929.dump`.
La migration et les projections répétées sont testées sur `gtm_crm_sync_test`, dans
le seul conteneur GTM. Ne jamais lancer un test destructif sur `gtm_crm`.

Le contrôle comprend les types de l'API et de la projection, la lecture MIME et les
identifiants, les réponses manuelles, les réservations, le changement de réservation,
la priorité des arrêts et l'absence de doublons.

Les serveurs utilisent actuellement le mode développement local. Les mises à jour du
code ou des dépendances demandent de refaire les vérifications. Le superviseur n'applique
aucune migration automatiquement. Un changement de machine ou de compte Windows demande
de révoquer/recréer la clé locale ; ne pas déplacer la copie chiffrée comme un mot de passe.

Une preuve locale devenue indisponible est signalée dans le résultat de projection.
Elle ne remplace pas par du vide le corps de message déjà importé dans le CRM.
