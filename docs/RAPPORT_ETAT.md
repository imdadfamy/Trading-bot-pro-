# Rapport d'état — 18 novembre 2026 (mis à jour en fin de journée)

## En une minute

TRADING INTELLIGENCE PRO est un **prototype de recherche** sur l'or (XAUUSD) et les indices synthétiques. Il est maintenant **connecté en lecture seule à un compte démo Deriv** et travaille sur de vraies données du courtier. **Aucun ordre n'a jamais été envoyé et aucun ne peut partir** : le mode observation et l'arrêt des nouvelles entrées sont actifs, l'envoi d'ordres est désactivé dans le code, et le bouton « Trading algo » du terminal est éteint.

- **Solide** : sécurité, journal infalsifiable, 113 tests, intégration continue verte, IA encadrée par des plafonds, connexion MT5 protégée en lecture seule, fenêtres de prudence autour des annonces américaines, deux interfaces en français.
- **Pas prêt** : l'expérience de 14 jours en démo reste bloquée par plusieurs conditions (passerelle d'exécution durable, rapprochement des ordres, arrêt d'urgence relié, etc.).
- **Aucun avantage de trading n'est démontré, et c'est confirmé sur de vraies données** : la stratégie de base perd sur le vrai XAUUSD (voir plus bas). C'est le comportement attendu d'une règle aussi simple, pas un échec de l'application.

## Où on en est, en chiffres

| Mesure | Valeur |
| --- | --- |
| Commits | plus de 20 sur `main`, dépôt public |
| Code Python | 33 modules, environ 3 600 lignes, plus 2 000 lignes de tests |
| Tests automatiques | 138 réussis, plus un test Node de navigation |
| Intégration continue GitHub | verte sur les commits vérifiés |
| Interfaces | 2 (aperçu local sans dépendance, version Next.js), 12 rubriques chacune |
| Documentation | 12 documents, 37 décisions datées dans `AVANCEMENT.md` |

## Ce que l'application fait aujourd'hui

| Fonction | État | Preuve |
| --- | --- | --- |
| Se connecter au compte démo Deriv, en lecture seule | Fonctionne | Compte démo confirmé, 10 000 $, aucun ordre |
| Lire les contrats (XAUUSD, indices synthétiques) | Fonctionne | XAUUSD : contrat de 100 oz, lot de 0,01 à 10, stops à 20 points |
| Exporter de vraies bougies avec l'écart réel (or et indices synthétiques) | Fonctionne | 4 séries de 5 000 bougies de 5 min |
| Contrôler la qualité des données selon les horaires du courtier | Fonctionne | Les pauses du courtier sont connues ; les autres trous restent refusés |
| Cycle de recherche (quatre rôles et un directeur) | Fonctionne sur données réelles, répond « attente » par prudence | Essai réel |
| Fenêtres de prudence autour des annonces américaines | Fonctionne | Emploi, inflation, prix à la production et Réserve fédérale, jusqu'en 2027 |
| Actualités (NewsAPI) avec tri de pertinence pour l'or | Testé en réel ; source gratuite en retard de 24 h | 99 titres sur 100 portent sur l'or |
| Étude des indices synthétiques (Volatility 75, Boom 500, Crash 500) | Fonctionne sur 17 jours de données réelles du compte démo, avec écart réel | Boom : sauts à la hausse seulement ; Crash : à la baisse ; écart de 2 à 19 % d'une bougie |
| Agents assistés par un modèle d'IA (`gpt-6.2-sol`) | Un essai réel plafonné a réussi | 3 appels pour 0,0075 $ |
| Pont d'ordres MT5 | Prêt mais **désactivé** ; choisit le bon mode d'exécution du symbole | Tests |
| Journal chaîné, sauvegardes, arrêt des entrées | Fonctionne (l'arrêt est un état enregistré) | Tests |

**Ce qu'elle ne fait pas** : envoyer un ordre, recevoir un flux de cours continu, surveiller le monde en continu, envoyer des alertes, ni utiliser un calendrier économique payant.

## Résultat de la stratégie de base sur de vraies données

Règle de croisement de moyennes 5 contre 20, objectif double, écart réel du courtier (coût complet : les bougies sont sur le prix vendeur), contrat réel de chaque instrument :

| Instrument | Trades | Facteur de profit | Espérance | Entraînement / validation / test |
| --- | --- | --- | --- | --- |
| XAUUSD (or) | 295 | 0,73 | −0,20 R (−2 441 $ sur 10 000 $) | 0,69 / 0,92 / 0,76 |
| Volatility 75 | 112 | 1,07 | +0,04 R | 1,35 / 1,07 / 0,63 |
| Boom 500 (exécution prudente des stops) | 253 | 0,96 | −0,03 R | 1,11 / 0,94 / 0,68 |
| Crash 500 (exécution prudente des stops) | 258 | 1,02 | +0,02 R | 1,04 / 1,10 / 0,86 |

Un facteur de profit sous 1 signifie que la règle perd. **L'or** perd sur les trois périodes : ce n'est pas un hasard d'échantillonnage. **Les indices** sont près de l'équilibre, mais l'écart avec le hasard est trop faible pour être réel (erreur typique d'environ 0,1 R) et la période de test, la seule vraiment à part, est sous 1 pour les trois. Aucun des quatre instruments ne montre d'avantage. Un banc d'essai plus exigeant (règles propres à chaque famille d'indices, comparées à des entrées au hasard) confirme : **aucune règle significative** sur Boom, Crash et Volatility 75, ce que Deriv annonce lui-même (aucun motif exploitable, tout motif historique est fortuit). Ce résultat est utile : il montre que les coûts réels pèsent et qu'une règle de croisement simple ne suffit pas. La suite est de chercher mieux, pas de la déployer. Note d'honnêteté : le premier chiffre publié pour l'or (0,78) sous-estimait les coûts ; un défaut du modèle de coûts a été corrigé (Décision 038).

## Ce que l'application peut apporter

Dit sans exagérer, parce que le trading est risqué et que beaucoup de stratégies qui semblent gagner disparaissent une fois les coûts et le hasard pris en compte.

- **Pour un particulier ou un chercheur** : un cadre pour tester une idée sur l'or ou sur des indices synthétiques **sans risquer d'argent**, avec des garde-fous (arrêt, plafonds, journal) et des données réelles du courtier.
- **Pour apprendre** : le dépôt est public, commenté en français, avec les limites de chaque résultat écrites noir sur blanc. Il montre comment encadrer une IA et comment un résultat flatteur sur données artificielles devient négatif sur données réelles.
- **Pour la méthode** : tout est traçable, reproductible et honnête sur ses limites.

Ce que ce n'est pas : un conseil en investissement, un robot qui fait gagner de l'argent, ni une preuve de performance.

## Ce qui a été intégré

- **Sécurité d'exécution** : mode observation, envoi d'ordres désactivé, intentions d'ordre uniques, résultats incertains jamais rejoués, rapprochement en lecture seule, mode d'exécution et distance des stops contrôlés sur le vrai contrat.
- **Compte MT5 démo** : connexion en lecture seule avec liste blanche de fonctions (aucune fonction de trading atteignable), refus de tout compte non démo, mot de passe jamais affiché.
- **Données** : bougies réelles du courtier avec écart, historique public Deriv, NewsAPI, calendrier officiel des annonces américaines.
- **Analyse** : agents déterministes, agents assistés par modèle avec prompts figés, comparateur, mémoire, études d'indices synthétiques.
- **Qualité et audit** : contrôle des bougies selon les horaires observés du courtier, journal vérifiable, sauvegardes, CI GitHub.
- **Interface** : 12 rubriques, libellés français partagés, explications par page, annonces à venir, largeur stable.

## Ce qu'il reste à faire

**Dépend de toi**
1. Activer le bouton « Trading algo » du terminal **uniquement** le jour où tu autoriseras un premier ordre démo (ce n'est pas nécessaire avant).
2. Relever les commissions et les horaires de session auprès de Deriv ou dans le terminal (l'API ne les donne pas) ; les horaires utilisés aujourd'hui sont observés, pas confirmés.
3. Plafond de dépense côté OpenAI.
4. Fixer les limites de risque et décider de la stratégie à figer pour l'expérience.

**Je peux le faire maintenant**
5. (Fait) Essai `order_check` à blanc : le courtier valide un ordre minimal sur l'or et les trois indices, sans exécution.
6. Étendre la recherche aux autres familles du compte (Drift Switching, DEX, Jump, Step) et accumuler plus de jours de données ; sur les familles testées, rien n'a battu le hasard.
7. Mesurer la qualité des prompts sur un jeu de cas préparés, et comparer `gpt-6-luna` à `gpt-6.2-sol`.
8. Frontend : composants shadcn/ui, accessibilité mesurée, tests automatisés.
9. Demander aux modèles de rédiger en français.

**Gros chantiers, après**
10. Passerelle MT5 durable, rapprochement après panne, arrêt d'urgence relié au programme d'exécution.
11. Production : PostgreSQL, API NestJS, Redis, authentification avec MFA, coffre de secrets, observabilité, déploiement.
12. Les conditions de la démo, puis l'expérience de 14 jours.

## Annonces américaines et calendrier économique

**Décision prise : pas de calendrier économique payant.** Les annonces programmées qui comptent pour l'or (emploi, inflation, prix à la production, Réserve fédérale) sont dans `config/us_events.json`, relevées sur les calendriers officiels. Autour de chacune, une fenêtre de prudence suspend les nouvelles entrées. Personne ne les saisit chaque jour : les dates sont publiées des mois à l'avance, la plus courte série couvre jusqu'au 3 décembre 2027, la mise à jour de la Réserve fédérale est une commande automatique, et l'application alerte avant l'expiration. Détails dans [ANNONCES_US.md](ANNONCES_US.md).

Limite honnête : une annonce **imprévue** n'est dans aucun calendrier. Elle est couverte par l'arrêt sur actualité critique, la limite d'écart et le cours périmé, ce qui réduit le risque sans le supprimer.

## Points d'attention

- **Dépôt public** : aucune clé ni base de données n'est suivie, vérifié avant chaque envoi. Les données du courtier restent hors de Git (licence du fournisseur).
- **Terminal MT5** : au démarrage sans compte enregistré, il affiche une fenêtre de connexion qui bloque l'application ; il suffit de la fermer. Garder le terminal ouvert évite le problème.
- **Coût de l'IA** : faible mais non nul ; le plafond local ne remplace pas celui d'OpenAI.
- **Qualité de l'IA** : non mesurée. Un accord avec la base déterministe n'est pas une preuve de justesse.
- **Données** : NewsAPI gratuit en retard de 24 h ; échantillon de 26 jours seulement pour le backtest.
- **Accès** : pas d'authentification multi-utilisateur ni de MFA ; ne pas exposer l'API sur Internet en l'état.
