# Runbook initial

- **Déconnexion MT5 / flux périmé :** bloquer les nouvelles entrées ; conserver les stops côté courtier ; vérifier positions et deals directement sur le terminal. Ne jamais rejouer une intention `sending` ou `uncertain` sans réconciliation.
- **Annonce américaine programmée :** pendant la fenêtre de prudence (voir `ANNONCES_US.md`), aucune nouvelle entrée ; le cycle répond « attente » avec la raison. Alerte d'expiration dans la rubrique Sessions : relancer `refresh-us-events`. Une annonce imprévue n'est pas dans le calendrier : s'appuyer sur l'arrêt sur actualité critique et la limite d'écart.
- **Annonce critique :** suspendre les nouvelles entrées et réévaluer les positions ; aucune inversion automatique.
- **Budget IA dépassé :** bloquer les nouveaux signaux dépendant des modèles ; continuer le suivi des positions.
- **Arrêt d'urgence :** l'API `POST /risk/kill-switch` maintient un état persistant actif et le journalise, mais l'intégration au worker MT5 n'est pas encore construite. Ne pas considérer cet endpoint comme une protection opérationnelle du courtier avant cette intégration.
- **Restauration :** la CLI crée une sauvegarde SQLite cohérente et vérifie la copie sans écraser la base active. Tester la restauration complète sur une instance isolée avant production. PostgreSQL exigera sa propre politique de sauvegarde et restauration avant mise en service.
- **Intégrité du journal :** appeler `GET /audit/integrity` avec la clé opérateur. En cas de `valid=false`, geler les nouvelles entrées, conserver une copie du fichier et rechercher la divergence avant toute reprise. La chaîne SHA-256 détecte des modifications accidentelles ; elle n'est pas une preuve contre un administrateur disposant de tous les accès.

## Incident d'ordre démo : procédure avant reprise

1. Maintenir l'arrêt des nouvelles entrées et identifier le `signal_id`. La liste de travail est `GET /orders/intents` avec `X-Operator-Key`, ou le nombre affiché dans Gestion des risques. Ne jamais renvoyer le même signal.
2. `reserved` signifie que l'envoi n'a pas été marqué comme commencé ; `sending` après un redémarrage, `uncertain` et une réponse sans ticket exigent une inspection humaine. `partial` signifie qu'une partie a pu être exécutée ; `accepted` n'est pas une preuve d'exposition finale. `preflight_rejected` ne doit pas être relancé par le même `signal_id`.
3. Confirmer sur le **compte DEMO attendu** le ticket, les ordres actifs et historiques, tous les deals, le volume restant, les positions et les stops. L'outil `reconcile_demo_ticket` ne fait qu'une inspection en lecture seule d'un ticket déjà connu ; l'absence d'enregistrement ne clôt pas l'incident.
4. Consigner la preuve et les actions de sécurité ; n'autoriser une reprise qu'après vérification indépendante des pertes, de l'exposition et des arrêts côté worker. Aucun mécanisme de reprise automatique n'est encore activé.
