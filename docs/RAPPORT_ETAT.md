# Rapport d'état — 18 novembre 2026

## En une minute

TRADING INTELLIGENCE PRO est aujourd'hui un **prototype de recherche** sur l'or (XAUUSD) et les indices synthétiques. **Aucun ordre ne peut partir** : l'application est en mode observation, l'arrêt des nouvelles entrées est actif, et aucun code actif ne se connecte à un compte de trading.

- **Solide** : sécurité, journal infalsifiable, 74 tests, intégration continue verte, IA encadrée par des plafonds de budget, deux interfaces en français.
- **Pas prêt** : l'expérience de 14 jours en démo reste bloquée par 14 conditions (compte MT5 démo, passerelle d'exécution, horaires du courtier, etc.).
- **Aucun avantage de trading n'est démontré.** Les profits affichés dans les exemples viennent de données artificielles.

## Où on en est, en chiffres

| Mesure | Valeur |
| --- | --- |
| Commits | 15, sur `main`, dépôt public |
| Code Python | 28 modules, environ 2 900 lignes, plus 1 250 lignes de tests |
| Tests automatiques | 74 réussis, plus un test Node de navigation |
| Intégration continue GitHub | verte sur les derniers commits |
| Interfaces | 2 (aperçu local sans dépendance, version Next.js), 12 rubriques chacune |
| Documentation | 11 documents, 32 décisions datées dans `AVANCEMENT.md` |

## Ce que l'application fait aujourd'hui

| Fonction | État | Preuve |
| --- | --- | --- |
| Lire des bougies (CSV, historique public Deriv) et contrôler leur qualité | Fonctionne | Essais réels sur 7 000 bougies |
| Cycle de recherche : quatre rôles puis un directeur | Fonctionne, répond presque toujours « attente » par prudence | Tests, essais |
| Backtests et évaluation chronologique 60/20/20 | Fonctionne sur données artificielles seulement | Tests |
| Actualités (NewsAPI) avec tri de pertinence pour l'or | Testé en réel ; la source gratuite a 24 h de retard | 99 titres sur 100 portent sur le marché de l'or après correction |
| Étude statistique des indices synthétiques (Volatility, Boom, Crash…) | Fonctionne sur 5 jours de données réelles | Boom : 8 sauts à la hausse, 0 à la baisse ; Crash : l'inverse |
| Agents assistés par un modèle d'IA (`gpt-6.2-sol`) | Un essai réel plafonné a réussi | 3 appels pour 0,0075 $ |
| Comparaison modèle contre base déterministe, notes en mémoire | Fonctionne | Tests |
| Journal chaîné SHA-256, sauvegardes, arrêt des entrées | Fonctionne (l'arrêt est un état enregistré) | Tests, essai dans l'interface |
| Interfaces en français, de 320 à 2 560 px de large | Vérifiées dans un navigateur | Contrôle du 18 novembre |

**Ce qu'elle ne fait pas** : trader, se connecter à MT5, recevoir un flux de cours en temps réel, surveiller le monde en continu, envoyer des alertes, ni utiliser le calendrier économique dans ses décisions.

## Ce que l'application peut apporter

Dit sans exagérer, parce que le trading est risqué et que beaucoup de stratégies qui semblent gagner disparaissent une fois les coûts et le hasard pris en compte.

- **Pour un particulier ou un chercheur** : un cadre pour tester une idée sur l'or ou sur des indices synthétiques **sans risquer d'argent**, avec des garde-fous (arrêt, plafonds, journal) déjà en place.
- **Pour apprendre** : le dépôt est public, commenté en français, avec les limites de chaque résultat écrites noir sur blanc. Il montre comment encadrer une IA (budget, sortie stricte, comparaison, mémoire) plutôt que de lui faire confiance.
- **Pour la méthode** : tout est traçable (qui a décidé quoi, avec quelles données, à quel coût), reproductible et honnête sur ses limites.

Ce que ce n'est pas : un conseil en investissement, un robot qui fait gagner de l'argent, ni une preuve de performance.

## Ce qui a été intégré

- **Sécurité d'exécution** : mode observation, aucun chemin d'envoi d'ordre, intentions d'ordre uniques, résultats incertains jamais rejoués, rapprochement en lecture seule.
- **Données** : import CSV, historique public Deriv sans compte, NewsAPI, calendrier Trading Economics (importé, pas encore utilisé).
- **Analyse** : agents déterministes, agents assistés par modèle avec prompts figés et versionnés, comparateur, mémoire, études d'indices synthétiques avec séparation hausses et baisses.
- **Qualité et audit** : contrôle des bougies, journal vérifiable, sauvegardes, CI GitHub.
- **Interface** : 12 rubriques, libellés français partagés entre les deux interfaces, explications claires par page, largeur stable, test de couverture des libellés.

## Ce qu'il reste à faire

**Dépend de toi**
1. Compte MT5 **démo** : courtier, serveur, identifiant, symboles exacts (XAUUSD et indices synthétiques), contrat, horaires, frais.
2. Plafond de dépense côté OpenAI.
3. Ajouter une licence au dépôt public (sans licence, personne n'a le droit de réutiliser le code).
4. Fixer les limites de risque et choisir la stratégie à figer pour l'expérience.

**Je peux le faire maintenant**
5. Mesurer la qualité des prompts sur un jeu de cas préparés, et comparer `gpt-6-luna` à `gpt-6.2-sol`.
6. Données XAUUSD réelles et backtest avec écart achat-vente et coûts.
7. Frontend : composants shadcn/ui, accessibilité mesurée (lecteur d'écran, contrastes), tests automatisés.
8. Fenêtres de prudence autour des grandes annonces (voir plus bas).
9. Demander aux modèles de rédiger en français (le texte renvoyé par le modèle reste en anglais).

**Gros chantiers, après le compte démo**
10. Passerelle MT5 durable, rapprochement après panne, arrêt d'urgence relié au programme d'exécution.
11. Production : PostgreSQL, API NestJS, Redis, authentification avec MFA, coffre de secrets, observabilité, déploiement.
12. Les 14 conditions de la démo, puis l'expérience de 14 jours.

## Le calendrier économique est-il nécessaire ?

**Non pour démarrer, et pas en version payante pour l'instant.**

- **Aujourd'hui il ne sert à rien dans les décisions** : les annonces importées s'affichent, mais aucun agent, ni le directeur, ni le contrôle de risque ne les lit. Payer maintenant n'améliorerait aucune décision.
- **Pour les indices synthétiques, il est inutile** : leurs cours ne réagissent pas aux annonces économiques.
- **Pour XAUUSD, il a une vraie valeur de sécurité** : autour des grandes publications américaines (emploi, inflation, réunions de la Réserve fédérale), l'or bouge vite et l'écart achat-vente s'élargit. Éviter les nouvelles entrées dans ces fenêtres est une protection simple.
- **Les dates de ces annonces sont publiques et connues à l'avance.** Une courte liste maintenue à la main (calendriers officiels des publications et de la Réserve fédérale) suffit pour une fenêtre de prudence, gratuitement.
- **Un abonnement payant ne se justifierait que plus tard**, si on veut comparer la valeur publiée à la prévision (la « surprise »), ce qui est de l'analyse avancée.

Recommandation : ne pas s'abonner, ajouter plus tard une liste locale de fenêtres de prudence reliée au contrôle de risque, et garder l'import Trading Economics en option.

## Points d'attention

- **Dépôt public** : aucune clé ni base de données n'est suivie, vérifié avant chaque envoi. L'adresse d'auteur Git y est visible. Prévoir une licence.
- **Coût de l'IA** : faible (moins d'un centime par cycle de trois agents) mais non nul ; le plafond local ne remplace pas celui d'OpenAI.
- **Qualité de l'IA** : non mesurée. Un accord avec la base déterministe n'est pas une preuve de justesse.
- **Données** : NewsAPI gratuit en retard de 24 h ; historique Deriv sans écart achat-vente donc inutilisable pour les coûts d'exécution.
- **Accès** : pas encore d'authentification multi-utilisateur ni de MFA ; ne pas exposer l'API sur Internet en l'état.
- **Incident corrigé le 18 novembre** : un test de la commande IA rechargeait le vrai `.env.local` ; il pouvait donc tenter un appel réel avec un faux nom de modèle (sans coût probable). Les tests sont maintenant étanches.
