# API locale d'observation

Exécuter `python -m trading_pro.server` depuis `backend` pour une API sans dépendances sur `127.0.0.1:8000`. La route `/` sert une interface locale autonome, `/preview.js` et `/preview.css` ses ressources fixes. L'adaptateur FastAPI `trading_pro.api:app` expose les mêmes lectures métier lorsqu'il est installé.

| Méthode | Route | Retour | Accès |
| --- | --- | --- | --- |
| GET | `/health`, `/dashboard`, `/readiness` | Santé, état d'observation et prérequis démo | Local |
| GET | `/market/snapshot`, `/market/candles`, `/news/events`, `/calendar/events`, `/sessions` | Données de recherche et fraîcheur | Local |
| GET | `/signals`, `/agents`, `/skills` | Décisions et catalogue | Local |
| GET | `/positions`, `/performance` | État indisponible sans MT5 | Local |
| GET | `/costs`, `/backtests`, `/experiments`, `/memory`, `/alerts` | Mesures et historique | Local |
| GET | `/synthetic/reports` | Études descriptives d'indices synthétiques enregistrées avec `analyze-synthetic --save` ; lecture seule, toujours `WAIT` | Local |
| GET | `/settings`, `/audit`, `/audit/integrity` | Paramètres versionnés, journal et vérification de sa chaîne | Clé opérateur |
| GET | `/export/signals.csv` | Export CSV du journal des signaux, cellules sécurisées | Clé opérateur |
| GET | `/orders/intents` | Intentions d'ordre à examiner ou à rapprocher ; lecture seule | Clé opérateur |
| PATCH | `/settings` | Configuration complète, `expected_version` et auteur | Clé opérateur |
| POST | `/experiments` | Brouillon de test, `mode=demo` | Clé opérateur |
| POST | `/risk/kill-switch` | Maintient l'arrêt actif | Clé opérateur |

La clé se transmet dans l'en-tête `X-Operator-Key`, définie seulement côté serveur par `TIP_OPERATOR_KEY`. Un opérateur peut ajouter `X-Operator-Name` pour le journal des paramètres. Aucune route HTTP n'arme le trading ni n'envoie un ordre. Le navigateur ne stocke pas la clé.

Exemple local de brouillon : `{"mode":"demo","strategy_version":"1.0"}`. Le démarrage du test de 14 jours reste bloqué par les prérequis du module `experiments.py` et l'absence du worker de production.
