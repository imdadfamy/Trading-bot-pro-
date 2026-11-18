# Préparation des trois environnements

## Vercel — frontend

Répertoire `web`, commande `npm run build`. `NEXT_PUBLIC_API_URL` doit pointer vers l'API HTTPS autorisée. Avant publication : lockfile, build CI, CORS limité, authentification et absence de secret dans les variables `NEXT_PUBLIC_*`.

## Railway — API et workers

La base locale SQLite ne convient pas aux workers distribués. Migrer vers PostgreSQL, Redis et une file durable ; ajouter migrations, health checks, rollback, sauvegardes et restauration. L'API de développement n'écoute que `127.0.0.1` volontairement. Ne pas déployer ce serveur en l'état.

## Contabo Windows — MT5

Installer le terminal et le package MetaTrader5 après choix du courtier et d'un compte DEMO. Passerelle sortante authentifiée vers Railway, aucune exposition publique de MT5/RDP, journal des ordres et réconciliation après redémarrage. Tester `order_check`, `order_send`, fills partiels, stops et connexion avec le compte démo. Le code ne contient aucun identifiant de compte.

## Go/no-go

Un brouillon d'expérience peut être créé localement. Son activation reste refusée jusqu'à validation de tous les prérequis dans `experiments.py`, y compris licences news, horaires du courtier, risque, idempotence, arrêts, alertes et sauvegardes. Aucun service payant n'est commandé par ce dépôt.
