# Planification et consommation

## Choix retenu

Un réveil horaire natif dans la tâche Desktop, utilisant les plugins de cette tâche
et le dossier local. Aucun daemon Python, agent CLI, modèle API ni sous-agent.
La définition préparée est dans docs/SCHEDULE_PROMPT.md. La surveillance de production
reste en pause tant que la bascule et le modèle ne sont pas vérifiés.

La documentation officielle décrit des tâches Desktop avec dossier local et choix
du modèle. Les déclencheurs Gmail événementiels y sont décrits comme web/mobile,
distincts de la planification locale. Sources consultées le 19 septembre 2026 :
[Tâches planifiées](https://learn.chatgpt.com/docs/automations?surface=app).

Le PC doit être allumé et éveillé, l'application ouverte, Internet disponible et
le dossier accessible. Pas de promesse de réponse PC éteint. Après interruption,
le scan complet, la pagination et la déduplication rattrapent les entrants.
La disponibilité de l'outil de planification ne prouve pas qu'une exécution a réussi.

Choisir GPT-6 Astra dans le sélecteur de la tâche. Un réveil dans cette tâche n'expose
pas ici de paramètre indépendant garantissant le modèle ; contrôler la sélection
et la première exécution. Ne jamais activer un repli automatique vers un autre modèle.
Si le modèle n'est pas disponible ou quota épuisé, suspendre et notifier le blocage.

## Mesure initiale

Une heure donne 24 réveils/jour, 168/semaine, 720 à 744/mois. Chaque réveil peut
impliquer plusieurs lectures Gmail et du raisonnement Astra : ce n'est pas gratuit
et illimité. L'abonnement existant couvre une allocation partagée avec les autres
usages. Le coût en quota par exécution ne peut pas être déduit du seul nombre d'emails.

Lors de l'audit, l'outil a indiqué Plus, 94 % de consommation de la fenêtre hebdomadaire
principale le 19/09. Le 20/09, un nouveau contrôle indique 4 % utilisés (96 % restants)
dans une nouvelle fenêtre hebdomadaire. Les autres réserves ne justifient pas une substitution de modèle. Aucun
crédit de remise à zéro consommé. Relever consommation avant/après 3–5 vrais contrôles
calmes puis avec entrant ; estimer 168 fois la consommation moyenne par contrôle.
Réduire cadence à 2–4 h si ce budget excède l'allocation disponible, en concertation
avec l'utilisateur. Le dispositif livré ne programme pas silencieusement ce changement.

Clay : workspace connecté, quota/credits restants non exposés par la lecture testée.
Aucun enrichissement payant lancé. Gmail/Calendly restent soumis à leurs limites
existantes. Calendly `is_paid:false` concerne l'événement, pas la formule du compte.

## GitHub Actions écarté

La chaîne distante serait : Gmail OAuth dédié → détecteur → événements durables →
déclenchement réel Astra Desktop → réponse via plugin → sauvegarde locale. La liaison
du détecteur distant vers cette exécution locale n'est pas démontrée. Un cron Linux
ne réveille pas à lui seul l'agent Desktop et ne dispose pas des connexions des plugins.
Un détecteur seul ne satisfait pas le besoin de réponses automatiques.

Aucun workflow Actions ni secret cloud installé. Consommation incrémentale Actions
de ce projet : 0 minute et 0 stockage d'artifact. Les tests s'exécutent localement.

À titre de comparaison, un job Linux horaire facturé 1 minute consommerait 720–744 min
mensuelles ; 2 minutes : 1 440–1 488 ; 3 minutes : 2 160–2 232. Il faudrait ajouter
tous les autres workflows, échecs/reprises, stockage et cache. Le quota personnel
restant n'a pas été attesté et aucune promesse « sous le quota gratuit » n'est faite.
GitHub indique des allocations dépendant du plan et une facturation au-delà :
[Billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage),
[Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Pour une future option cloud : runner Linux standard, plafond bloquant les dépenses,
budget réel tenant compte des autres usages, authentification Gmail limitée dédiée,
secret store, pagination, reprise et état durable seraient indispensables. Non configurés
car cette option n'apporte pas de déclenchement Astra vérifié. Les runners éphémères et
le cache ne sont pas une base durable. Les retards du cron restent possibles.

Une API Astra ou exécution cloud séparée changerait l'architecture et le financement.
L'API est tarifée séparément ; elle n'a pas été activée. Le tarif officiel consulté
est 10 USD/M tokens entrants et 50 USD/M tokens sortants hors autres coûts et paliers :
[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra).
