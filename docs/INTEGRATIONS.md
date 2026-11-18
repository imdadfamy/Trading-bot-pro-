# Intégrations à renseigner après remise des API

| Domaine | Adaptateur prévu | Informations indispensables | État |
| --- | --- | --- | --- |
| Broker XAUUSD | Terminal MT5 Windows, passerelle sortante | Courtier, compte DEMO, serveur, contrat, taille/valeur tick, commissions, heures, politiques stops et filling | Non connecté |
| Modèles IA | Interface `Provider` avec sorties JSON strictes | Fournisseur, clé côté serveur, modèle/version, plafond par appel et tarifs vérifiés | Adaptateur, prompts figés et orchestration prêts (`analyze-with-models`) ; jamais testé avec une vraie clé ni des tarifs vérifiés |
| Actualités | Sources officielles, fournisseur sous licence | Accès, droits de conservation, latence, couverture, schémas d'alertes/rétractations | Import JSON local seulement |
| Calendrier économique | API sous licence | Consensus point-in-time, révisions, heures UTC et embargo | Non connecté |
| Intermarket | API de marché licenciée | DXY, rendements, futures, fréquence, fuseaux, coûts | Non connecté |
| Alertes | Canal choisi par l'opérateur | Destinataire, secret côté serveur, test de livraison | Journal local seulement |
| Indices synthétiques | Export CSV du compte démo MT5 ou historique public du fournisseur, analyse hors ligne | Courtier, symboles exacts, contrat, bid/ask, horaires, trous de données | Historique public Deriv récupérable à la demande (`fetch-deriv-candles`, sans authentification) et analyse descriptive hors ligne (`analyze-synthetic`) ; aucune exécution |

Pour brancher un fournisseur, ajouter un adaptateur qui normalise les événements avant stockage et ne transmet aux agents que les champs nécessaires. Conserver les clés dans un coffre côté serveur ; aucune clé dans `NEXT_PUBLIC_*`, dans SQLite ou dans les journaux. Ne pas activer automatiquement le mode démo lorsqu'une clé est renseignée.

Les dépôts tiers de stratégies mentionnés dans le cahier des charges ne sont ni installés ni exécutés. Leur licence, origine et qualité restent à auditer.

## Contrat du pont MT5 avant branchement

L'adaptateur `MT5DemoBroker` est désactivé par défaut. Un compte DEMO est revérifié au précontrôle et juste avant l'appel `order_send`. Un code `DONE_PARTIAL` est suivi comme exécution partielle ; `PLACED`, timeout et autres réponses non conclusives restent `uncertain`. `order_check` valide la requête, mais ne garantit pas qu'un ordre sera exécuté. Une réservation d'intention empêche tout deuxième envoi du même `signal_id`.

Le rapprochement actuel est une inspection **en lecture seule** du ticket d'ordre connu. Il exige le numéro attendu du compte DEMO et compare symbole, identifiant `magic`, ticket et deals. Un historique MT5 vide, absent ou indisponible ne prouve pas qu'aucun ordre n'est parti. Un ticket inconnu ne peut pas être rapproché automatiquement ; il faut inspecter le compte auprès de l'opérateur. Les deals observés ne prouvent pas à eux seuls que les stops sont en place ni que toute l'exposition est clôturée. Le worker durable et la procédure de reprise restent à implémenter avant toute démo automatique.

Références du fournisseur : [order_check](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py), [order_send](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py), [codes de retour](https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes), [historique des deals](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py).
