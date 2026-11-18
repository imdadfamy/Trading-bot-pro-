# Architecture et frontières de confiance

## Flux local implémenté

CSV horodaté → validation OHLC → stockage SQLite → cycle immuable → quatre rapports → directeur → signal WAIT → journal. Le backtest est séparé du cycle décisionnel et de MT5. Un `DemoBroker` simule uniquement un résultat logiciel ; ce n'est pas un courtier. Le pont MT5 n'est exposé par aucune route et n'est pas activé.

## Famille synthétique (hors ligne)

Les indices synthétiques ne partagent pas les preuves de XAUUSD : ni annonces, ni sessions forex, ni fondamentaux. `synthetic_research.describe` lit des bougies closes d'un seul courtier et d'un seul symbole et produit des statistiques descriptives (dispersion, fréquence de mouvements extrêmes, intervalle de Wilson indicatif, découpage chronologique 80/20). La sortie est toujours `WAIT` : elle n'alimente ni le directeur, ni le risque, ni MT5.

## Frontières

- Données externes : non fiables ; le normaliseur conserve source, URL, publication, réception et validation. Une rumeur critique suspend une entrée, sans produire seule une direction.
- Agents : produisent des rapports, sans secrets, sans permissions de mutation du courtier. Le directeur ne peut pas changer les limites.
- Risque : calcul indépendant, arrêt par défaut, refus si compte non démo, prix ou métadonnées non finis, cotation périmée, budget épuisé, limite journalière ou stops invalides.
- Ordres : intention idempotente persistée avant envoi. Après timeout, état incertain à réconcilier. La passerelle de production doit authentifier chaque commande, valider le compte démo et vérifier les stops côté broker.
- Interface : lecture publique sur `127.0.0.1` uniquement en mode développement ; mutations avec clé d'opérateur. Ceci n'est pas une authentification multi-utilisateur ou MFA.

## Cible de production non implémentée

Vercel pour Next.js, Railway pour API NestJS, workers Python, PostgreSQL et Redis ; Contabo Windows pour le terminal MT5 et une passerelle sortante authentifiée. Le stockage SQLite est local seulement. Aucune mise en service avant migration, contrôle des rôles/MFA, coffre de secrets, tests de restauration, CI validée et recette du compte démo.

## Données et calculs

Horodatage UTC dans le stockage ; sessions calculées par fuseau local, avec repli limité aux règles DST depuis 2007 si `tzdata` manque sur Windows. En production, installer `tzdata` pour l'historique complet. Les volumes tick MT5 ne sont pas un volume mondial. Le jeu CSV fourni est explicitement synthétique : ses résultats ne mesurent aucune performance de marché.
