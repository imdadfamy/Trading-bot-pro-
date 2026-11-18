# Cahier des charges vivant — addendum et historique

Référence : cahier des charges du 17 novembre 2026, 22 pages, conservé dans la Library de l'utilisateur. Ce fichier complète la référence sans prétendre la remplacer.

## 18 novembre 2026 — Décision 001

Le développement commence dans un dossier vierge. Premier incrément : cœur Python testable, journal SQLite et interface Next.js. La cible de production Next.js/NestJS/Prisma/PostgreSQL/Redis reste au cahier des charges. SQLite est limité au prototype local, sans multi-worker.

## Décision 002 — Sécurité de l'exécution

Le mode initial est observation, kill switch actif. L'adaptateur MT5 exige `ACCOUNT_TRADE_MODE_DEMO`; l'API n'expose aucune route d'envoi d'ordres. Les intentions sont idempotentes, les résultats incertains ne sont jamais renvoyés automatiquement. Une intégration sécurisée et une réconciliation des deals/positions sont nécessaires avant le test de 14 jours.

## Décision 003 — IA et skills

Catalogue des 27 compétences documenté et versionné comme spécifications de recherche. Les analyses existantes sont des baselines déterministes qui s'abstiennent ; ni fournisseur LLM ni preuve de performance ne sont branchés. Modèles et budgets paramétrables via API authentifiée en mode observation.

## Reste à développer / critères bloquants

- Ingestion broker et news sous licences, fraîcheur et calendrier point-in-time ; surveillance continue et alertes critiques.
- Agents complets, sorties JSON strictes, orchestration durable, mémoire, coûts, comparateur et prompts figés.
- Migrations PostgreSQL, API NestJS, Redis, files, WebSocket, authentification utilisateur/MFA et coffre de secrets.
- Réconciliation MT5, protections SL/TP contrôlées, ordres partiels, politique de fermeture de sécurité, tests de panne et connecteur sortant authentifié.
- Backtests avec bid/ask et coûts, sessions avec DST, rapports et expérimentation de 14 jours après recette et validation des paramètres.
- Douze écrans pleinement fonctionnels, composants shadcn/ui et React Bits audités, accessibilité, thèmes et tests.
- CI/CD, sauvegardes, observabilité et déploiement Vercel/Railway/Contabo après autorisation des dépenses.

## Historique de validation

18 novembre 2026 : huit tests unitaires du noyau réussis, compilation Python réussie. Installation `pip install -e ./backend` impossible dans cet environnement : résolution DNS vers PyPI indisponible. Installation npm interrompue après absence de réponse du registre ; dépendances frontend non présentes. API FastAPI et build Next.js non exécutés. Aucun test externe ni performance de trading attesté.

## 18 novembre 2026 — Décision 004 : parcours hors ligne

Ajout d'une API d'observation Python standard sur `127.0.0.1`, sans route de trading, pour pouvoir travailler avant l'installation des dépendances. Import CSV horodaté, cycle immuable, stockage des rapports, signaux WAIT, coûts, paramètres versionnés et backtest de référence. Les douze rubriques frontend lisent les routes locales ; le build Next.js reste non vérifié faute d'accès npm.

Jeu `examples/synthetic_xauusd.csv` généré pour les tests, sans relation avec le marché réel. Les gains du backtest sur ce jeu ne sont pas des résultats commerciaux ou une preuve de stratégie. Horodatage du cycle calé sur la clôture historique du CSV afin de ne pas présenter une ancienne cotation comme live.

## 18 novembre 2026 — Décision 005 : expérimentation

Création de brouillons de 14 jours avec configuration figée et liste de prérequis. `start` refuse même si tous les booléens de recette sont fournis : il manque encore un worker durable, une passerelle authentifiée et la réconciliation réelle du compte démo. Aucune connexion MT5 ni activation de trading réel. Vingt tests locaux passent, dont un test du gestionnaire HTTP en mémoire ; la sandbox empêche les requêtes sur le socket local, donc le transport réseau n'a pas été testé de bout en bout ici.

## 18 novembre 2026 — Décision 006 : interface opérateur

L'interface offre la consultation des modules, le réglage des modèles et des budgets par API authentifiée, et l'activation persistante de l'arrêt des nouvelles entrées. La clé n'est pas écrite dans le stockage du navigateur. Il manque toujours MFA et contrôle multi-utilisateur avant exposition réseau.

Le dépôt Git local a été initialisé, mais l'index `.git/index.lock` est refusé en écriture par les permissions de cet environnement. Aucun commit n'a été créé ; le présent fichier conserve l'historique jusqu'à résolution de ce droit d'accès. Les 27 fiches du projet ne sont pas installées comme compétences personnelles de ChatGPT.

## Décisions techniques encore nécessaires

Compte et courtier démo, contrat XAUUSD et caractéristiques des lots, sources/licences news et marché, clés de modèles, stratégie mesurable, enveloppes approuvées, services d'hébergement. La phase d'intégration et la recette seront possibles après fourniture de ces éléments ; aucune dépense automatique.

## 18 novembre 2026 — Décision 007 : révisions et garde-fous des données

L'import JSON d'actualités conserve plusieurs versions d'un même événement et rejoue l'état reçu à la date d'analyse ; les démentis ultérieurs ne sont pas appliqués rétroactivement. Le calcul du volume exige maintenant commissions et hypothèse de glissement explicites du courtier, en plus de la taille et valeur du tick. Les événements d'exemple sont synthétiques.

## 18 novembre 2026 — Décision 008 : évaluation chronologique

Ajout d'une évaluation fixe 60/20/20 (entraînement, validation, test) sans chevauchement des périodes ni ajustement des paramètres sur le test. C'est un diagnostic logiciel sur des données synthétiques, pas une validation statistique ou un walk-forward complet sur des données de marché réelles.

## 18 novembre 2026 — Décision 009 : aperçu local et qualité des données

Interface locale autonome servie par l'API standard sur `127.0.0.1`, avec douze rubriques, courbe d'historique, réglages et commande d'arrêt. Elle fonctionne sans le registre npm, tandis que la version Next.js reste la cible Vercel. Contrôle des bougies : ordre chronologique, doublons, trous, clôture future, fraîcheur et valeurs aberrantes ; rejet du cycle si le jeu échoue. Les horaires de fermeture du courtier ne sont pas encore connus, donc les pauses planifiées ne sont pas automatiquement admises.

Le journal local possède une chaîne de hachages SHA-256 vérifiable par API authentifiée. Vingt-huit tests unitaires passent, ainsi qu'une vérification syntaxique du JavaScript de l'aperçu. L'ouverture effective d'un socket demeure interdite dans cet environnement, et le build Next.js n'est toujours pas validé faute d'accès aux dépendances.

## 18 novembre 2026 — Décision 010 : sauvegarde locale

La CLI produit une sauvegarde SQLite cohérente et vérifie l'intégrité SQLite ainsi que la chaîne du journal dans la copie. Un test de restauration opérationnelle sur infrastructure isolée et la politique PostgreSQL restent à réaliser avant déploiement.

## 18 novembre 2026 — Décision 011 : interface locale exploitable

La route `/` sert un aperçu autonome avec les douze écrans, courbe d'historique, statut de fraîcheur, réglages authentifiés et bouton d'arrêt. Les données sont injectées comme texte, sans exécution HTML des sources. L'API expose un export CSV de signaux réservé à l'opérateur et protège les cellules contre les formules de tableur. Le Budget Center indique les plafonds enregistrés et le blocage des nouveaux appels.

Ces contrôles n'équivalent pas à une recette du frontend Next.js, du terminal MT5 ou des fournisseurs. Les composants React Bits et shadcn/ui ne sont pas encore intégrés faute de registre npm accessible ici.

## 18 novembre 2026 — Décision 012 : vérification par l'utilisateur

`Start-Local.ps1` lance les vérifications, charge les jeux synthétiques de façon idempotente, génère une clé opérateur temporaire et démarre l'interface locale au premier plan. `Verify-Local.ps1` vérifie 28 tests, la compilation Python et la syntaxe de l'aperçu. La route `/readiness` distingue explicitement la revue locale possible du test démo encore bloqué. Le gestionnaire HTTP des paramètres et de l'arrêt est testé en mémoire. Le démarrage réseau effectif doit être confirmé sur le PC de l'utilisateur, car les sockets de cet environnement sont restreints.

## 18 novembre 2026 - Décision 013 : lisibilité et stabilité de l'interface

Le guide utilisateur explicite le bon chemin Windows, la commande PowerShell 5 compatible, les douze rubriques et les limites du jeu synthétique. La navigation de l'aperçu local ignore les réponses API arrivées après un changement de rubrique et réserve la place pendant le chargement. Les noms des rubriques sont présentés en français ; les panneaux, la navigation et les lignes longues ont été ajustés pour éviter les déplacements visuels et les débordements. Le frontend Next.js annule les requêtes d'anciennes rubriques et évite les requêtes de tableau de bord simultanées. Ces corrections ne remplacent pas une revue visuelle sur le PC de l'utilisateur.

Le contrôle local exécute 28 tests Python et un test Node qui simule des réponses API arrivant dans le désordre lors d'un changement de rubrique. Le build Next.js reste non vérifié car ses dépendances ne sont pas installées dans cet environnement.

Le logiciel n'est pas encore au stade « seules les clés API manquent » : la passerelle MT5 et sa réconciliation, l'authentification de production, les composants d'interface prévus, le stockage distribué et la recette de la démo restent des travaux distincts. Cette distinction est maintenue dans le guide et dans `/readiness`.

## 18 novembre 2026 - Décision 014 : intentions MT5 et rapprochement prudent

L'adaptateur MT5 ne peut pas envoyer par défaut, même lorsqu'une instance du terminal est injectée : le drapeau `demo_execution_enabled` doit être fourni explicitement en code et aucune route HTTP ne l'active. Le mode DEMO, les cotations, le volume et `order_check` sont revérifiés juste avant l'envoi. Le moteur rejette les snapshots expirés avant réservation de l'intention.

Une intention est réservée une seule fois. Les transitions de statut sont atomiques et vérifient l'ancien état ; un worker obsolète ne peut pas écraser une observation plus récente. Une prévalidation refusée est enregistrée séparément d'un envoi incertain. `DONE_PARTIAL` reste partiel ; les autres codes non conclusifs restent incertains et ne sont jamais renvoyés automatiquement. Le rapprochement en lecture seule d'un ticket connu exige le numéro du compte DEMO attendu et compare le symbole, le magic et les tickets des ordres et deals ; l'absence de résultat ne prouve jamais l'absence d'exécution. Une intention sans ticket exige un examen humain. La route authentifiée `/orders/intents` donne la liste à examiner et le tableau de bord son nombre.

Le rapprochement d'un véritable compte démo n'a pas été exécuté, aucun compte n'étant connecté. Une passerelle durable, la gestion des fills partiels, la vérification des stops sur les positions et la recette sur le contrat du courtier restent indispensables. La suite locale valide 32 tests Python et un test Node de navigation ; aucun ordre n'a été envoyé.

## 18 novembre 2026 - Décision 015 : préparation des accès fournisseurs

Ajout d'un contrôle des variables d'environnement qui ne retourne que des booléens et ne prétend jamais attester une connexion. `/readiness` reste bloqué pour la démo même si toutes les clés sont présentes. L'adaptateur NewsAPI effectue un appel explicite borné, sans redirection ni clé dans l'URL, et importe uniquement des titres non confirmés, sans effet directionnel sur XAUUSD. La commande CLI `poll-newsapi` n'est pas planifiée en tâche de fond. Le plan développeur NewsAPI retarde les articles de 24 heures et ne convient pas à la veille immédiate demandée.

Un adaptateur OpenAI Responses à sortie JSON stricte est prêt à être appelé explicitement par le moteur après configuration des tarifs du modèle. Il n'est branché ni au serveur local ni à l'exécution d'ordres ; son usage n'a pas été testé avec une clé réelle. Les coûts rapportés par le fournisseur sont désormais comptabilisés même si l'appel dépasse le plafond projeté, puis le rapport est refusé. Le plafond local n'est pas une garantie absolue de facturation : configurer aussi un plafond côté fournisseur et valider les tarifs. La liste officielle des accès et les limites de chaque offre sont documentées dans `ACCES_API.md`.

Le calendrier Trading Economics, les données intermarket, la surveillance mondiale continue, la passerelle MT5 durable, l'authentification de production et le build Next.js restent à finaliser. Trente-six tests Python et un test Node passent hors réseau. Aucune API payante n'a été appelée et aucune dépense n'a été engagée.

## 18 novembre 2026 - Décision 016 : calendrier économique reçu par versions

Un adaptateur Trading Economics lit explicitement le calendrier des États-Unis en utilisant la clé dans l'en-tête HTTP, sans redirection et avec une limite de taille. Les événements sont normalisés et chaque état reçu est conservé avec son heure de réception ; une révision future ne modifie pas une analyse historique. `/calendar/events` et l'écran Actualités et marché affichent les données importées. La commande `poll-calendar` n'est pas planifiée et n'a aucun effet sur les ordres ou les signaux. Le contrat de licence, les autres pays, les flux continus et la classification des annonces critiques doivent encore être validés. Trente-huit tests Python et le test de navigation passent ; aucune clé réelle n'a été utilisée.

## 18 novembre 2026 - Décision 017 : fichier local des clés

Création de `.env.local` à la racine, avec emplacements vides pour OpenAI, NewsAPI, Trading Economics et les identifiants du compte MT5 DEMO. Le mot de passe MT5 reste vide et n'est utilisé par aucune passerelle. `.gitignore` exclut `.env.local` et les variantes locales. Un chargeur minimal lit uniquement les noms autorisés, ignore les lignes vides, préserve les variables déjà définies dans le processus et ne reprend jamais la valeur d'un secret dans une erreur. CLI, serveur local et FastAPI le chargent au démarrage. `Start-Local.ps1` continue à générer sa propre clé opérateur temporaire. L'ajout de valeurs ne déclenche aucun appel API ou ordre.

Trente-neuf tests Python et le test Node de navigation passent. `git check-ignore .env.local` confirme l'exclusion. Le contenu local du fichier n'est pas sauvegardé ni transmis par l'application.

## 18 novembre 2026 - Décision 018 : premier commit et état des lieux

Le dépôt Git local n'avait aucun commit : le blocage d'écriture sur `.git/index.lock` signalé à la décision 006 ne se reproduit plus, `git add` fonctionne. Le premier commit (89 fichiers) est créé sur la branche `master`. Avant le commit, l'index a été contrôlé : `.env.local`, les bases `*.db` et les dossiers générés sont bien exclus par `.gitignore`, et une recherche de motifs de clés ou de mots de passe dans les fichiers suivis n'a rien trouvé. L'historique Git prend désormais le relais de ce fichier pour tracer les modifications ; ce document continue de consigner les décisions et les limites.

État vérifié ce jour : 39 tests Python et le test Node de navigation passent, la compilation Python réussit. Le build Next.js n'a pas encore été lancé : Node.js et npm sont présents sur le PC de l'utilisateur, mais `npm install` n'a pas été exécuté. `OPENAI_API_KEY` et `TIP_NEWSAPI_KEY` sont renseignées dans `.env.local`, sans avoir été utilisées ni testées par un appel réel ; `TIP_TRADING_ECONOMICS_KEY` et le compte MT5 DEMO sont vides. `/readiness` reste bloqué pour les 14 jours et `ExperimentManager.start` refuse toujours l'activation.

Prochaines étapes, par ordre : installer les dépendances et valider `npm run build` ; tester un appel volontaire NewsAPI ; fournir le compte et le contrat MT5 DEMO ; construire la passerelle durable et la réconciliation ; brancher l'orchestration IA ; données de marché réelles et backtest avec bid/ask ; authentification, MFA et migration PostgreSQL avant tout déploiement. La liste complète reste dans « Reste à développer / critères bloquants ».

## 18 novembre 2026 - Décision 019 : build Next.js validé et branche principale

La branche locale `master` est renommée `main`, nom de la branche principale prévu pour les futures demandes de fusion. `npm install` dans `web` a installé 30 paquets et créé `web/package-lock.json`, désormais suivi pour des builds reproductibles. `npm run build` réussit avec Next.js 16.4.6 : compilation, vérification TypeScript et génération des pages statiques `/` et `/_not-found`. Next.js a mis à jour `tsconfig.json` et `next-env.d.ts` automatiquement ; ces changements sont conservés.

Ce build prouve seulement que le frontend compile. Il n'a pas été ouvert dans un navigateur contre l'API ni revu visuellement, et aucun audit des dépendances n'a été exécuté (`--no-audit`). Les composants shadcn/ui et React Bits, l'accessibilité, les thèmes et les tests du frontend restent à faire. Le point « build Next.js non vérifié » des décisions précédentes est donc levé pour la compilation uniquement.

## 18 novembre 2026 - Décision 020 : étude des indices synthétiques

Recherche des sources officielles Deriv sur les familles d'indices, les historiques publics et les limites des motifs statistiques ; synthèse et critères d'entrée dans `INDICES_SYNTHETIQUES.md`. Ajout d'une commande locale `analyze-synthetic` : statistiques descriptives sur un seul symbole/courtier, séparation chronologique et incertitude affichée. Aucun score prédictif, signal d'entrée, flux en direct ou ordre n'est ajouté. L'historique public Deriv et le compte MT5 restent à vérifier avant toute utilisation démo.

## 18 novembre 2026 - Décision 020 : vérification de l'interface Next.js dans un navigateur

`npm run dev` (Next.js 16.4.6) a été ouvert dans le navigateur intégré, avec l'API locale d'observation déjà active sur `127.0.0.1:8000`. Résultat : la page se charge, la console ne remonte aucune erreur, l'alerte « API déconnectée » n'apparaît pas et les douze rubriques s'affichent sans erreur. Le bandeau MODE OBSERVATION, le bouton ARRÊT D'URGENCE et l'indication « Démo uniquement » sont visibles. API & Integrations affiche `ready_for_14_day_demo = false` avec les conditions bloquantes, Skills Library liste les 27 fiches, Risk Center indique kill switch actif et courtier déconnecté.

Limites : la vérification est un parcours fonctionnel à largeur réduite (environ 800 px), pas une revue visuelle complète ni un test mobile. Les réglages et l'arrêt d'urgence n'ont pas été exercés depuis Next.js (aucune clé opérateur saisie). Les rubriques Agents, Mémoire, Backtests et Signaux sont vides car la base locale ne contient pas de cycle ; `Start-Local.ps1` charge le jeu synthétique. Constats d'interface à corriger : les noms des conditions bloquantes se coupent au milieu des mots dans la carte étroite de API & Integrations, les valeurs sont affichées en `true`/`false` brut et les libellés des rubriques sont en anglais alors que l'aperçu local est en français. `next dev` génère `web/AGENTS.md` et fait basculer `next-env.d.ts` entre les chemins `.next/dev` et `.next` ; le fichier suivi reste la version issue du build.

## 18 novembre 2026 - Décision 021 : corrections de l'interface Next.js

Les trois défauts relevés à la décision 020 sont corrigés dans `web/app/` : les conditions bloquantes de Intégrations sont des pastilles distinctes qui ne se coupent plus au milieu des mots ; les booléens s'affichent « Oui » / « Non » ; les rubriques, le fil d'Ariane et les champs des tableaux d'état sont en français, avec les mêmes libellés que l'aperçu local. Les clés d'API et les routes restent inchangées, seuls les libellés changent. `npm run build` réussit. Le parcours des douze rubriques sur le build de production, à environ 800 px de large, n'affiche aucune alerte ni débordement horizontal. La page Intégrations a été contrôlée visuellement.

Reste non vérifié : affichage mobile étroit, thème clair, accessibilité (lecteur d'écran, contrastes), et test des réglages et de l'arrêt d'urgence depuis Next.js avec une clé opérateur. Les textes d'introduction de certaines rubriques ne reprennent pas encore les explications plus détaillées de l'aperçu local.

## 18 novembre 2026 - Décision 022 : recette des réglages, de l'arrêt d'urgence et du mobile

Test bout en bout de l'interface Next.js (build de production) contre une API locale **isolée** : base temporaire, port 8001, clé opérateur jetable, sans lien avec une base ou une clé réelle. Résultats : les paramètres se chargent avec la clé, une modification du budget quotidien est enregistrée côté serveur (version 0 vers 1) ; l'API répond 403 sans clé ou avec une mauvaise clé ; le bouton ARRÊT D'URGENCE reste inactif sans clé et, avec la clé, enregistre l'événement `risk.kill_switch` ; le journal contient aussi `settings.changed` et la vérification `/audit/integrity` renvoie `valid: true`. À 375 px de large, cinq rubriques sont contrôlées sans débordement horizontal, et la liste des conditions bloquantes reste lisible.

Ces essais valident l'interface et l'API locale, pas la protection d'une passerelle MT5, qui n'existe pas encore : l'arrêt reste un état persisté dans l'API. Une correction d'espacement a été ajoutée sous le texte d'introduction des paramètres. `web/AGENTS.md`, généré par `next dev`, est maintenant suivi par Git. Non vérifiés : accessibilité complète au lecteur d'écran, contrastes mesurés, navigateurs autres que celui intégré. Le thème est volontairement sombre uniquement.

Trois fichiers apparus pendant la session hors de ces modifications (`synthetic_research.py`, son test et `docs/INDICES_SYNTHETIQUES.md`, ainsi qu'une commande `analyze-synthetic` dans `cli.py`) n'ont pas été intégrés à ce commit : leur auteur doit les valider et les commiter. Avec eux, la suite locale compte 41 tests Python, tous réussis.

## 18 novembre 2026 - Décision 023 : analyse des indices synthétiques

L'étude des indices synthétiques (Volatility, Boom/Crash, Step, Jump, Range Break) rejoint le projet comme famille distincte de XAUUSD, avec sa note [INDICES_SYNTHETIQUES.md](INDICES_SYNTHETIQUES.md). Premier outil : la commande `analyze-synthetic` (module `synthetic_research.py`), une analyse **statistique descriptive hors ligne** de bougies closes d'un seul courtier et d'un seul symbole : dispersion par bougie, fréquence des mouvements dépassant un seuil, intervalle de Wilson indicatif, découpage chronologique 80/20 et drapeau `statistically_sufficient` (au moins 100 rendements, dont 30 dans la dernière période). La sortie reste `WAIT` et n'est reliée ni au directeur, ni au risque, ni au pont MT5. Les annonces, sessions forex et fondamentaux ne sont pas des preuves pour cette famille.

Vérification : trois tests dédiés (rapport descriptif, rejet de symboles ou courtiers mélangés, de seuils invalides, de bougies qui se chevauchent, comptage des sauts) et un essai de la commande sur le jeu artificiel, qui n'est pas un historique d'indices synthétiques et ne permet aucune conclusion sur ces marchés. Limites : aucun historique réel d'indices synthétiques n'a été collecté ; la disponibilité des symboles et leurs contrats sur le compte MT5 démo restent à confirmer ; l'intervalle de Wilson suppose des observations indépendantes ; aucune stratégie, aucun backtest d'exécution ni intégration au tableau de bord ou à l'API n'existe pour cette famille.

## 18 novembre 2026 - Décision 024 : état de la CI et hygiène du dépôt

Le dépôt GitHub est **privé** : l'API publique renvoie 404 sans authentification et le navigateur intégré, non connecté à GitHub, ne voit pas l'onglet Actions. Le résultat du workflow `core-checks` n'a donc pas pu être lu depuis cet environnement ; il reste à confirmer par l'utilisateur dans l'onglet Actions. Les mêmes commandes ont été exécutées localement avec succès (tests Python, compilation, test Node, `npm run build`).

Corrections : ajout de `.gitattributes` (normalisation des fins de ligne, binaires déclarés) pour supprimer les avertissements LF/CRLF ; `Verify-Local.ps1` lance désormais aussi `npm run build` lorsque `web/node_modules` existe et signale sinon qu'il est ignoré ; les deux scripts PowerShell sont enregistrés en UTF-8 avec BOM, car PowerShell 5 affichait les accents de travers (« VÃ©rifications »). Le message de réussite s'affiche maintenant correctement. Aucun compte de tests n'est codé en dur dans les scripts ; les mentions « 28 tests » des décisions précédentes sont historiques.
