# Premier ordre démo supervisé

**À quoi ça sert.** Vérifier, une fois, que la chaîne complète fonctionne sur le compte démo : envoi d'un ordre minimal avec stop et objectif, retour du courtier, rapprochement, fermeture. **Ce n'est pas un test de stratégie** : l'analyse ne produit aucun signal d'achat ou de vente, l'ordre est donc forcé à la main. Le risque est de l'ordre de 1 $ sur un compte fictif.

**Qui fait quoi.** Cette procédure est lancée **par toi**. Le programme ne peut pas la déclencher seul, et l'assistant ne l'exécute pas. Chaque étape ci-dessous est une action volontaire.

## Les garde-fous (tous doivent passer, dans cet ordre)

1. **Phrase exacte tapée par toi**, qui nomme le sens et le symbole.
2. **Aucune fenêtre d'annonce américaine** en cours, et calendrier valide (mode strict).
3. **L'arrêt des nouvelles entrées levé volontairement**, par une commande dédiée avec phrase et motif consignés au journal. Il est **réarmé après chaque tentative**, réussie ou refusée : une levée autorise une seule tentative.
4. **Compte démo confirmé**, « Trading algo » **allumé par toi** dans le terminal, aucune position déjà ouverte sur le symbole.
5. **Le vrai moteur de risque approuve** (limites de perte, écart maximal, cours à jour), puis **le courtier valide la requête exacte** (`order_check`) juste avant l'envoi.
6. **Seul le plus petit volume autorisé** est envoyé, avec un stop et un objectif au-delà du minimum du courtier (trois fois le niveau minimal plus l'écart).

Après l'envoi : rapprochement en lecture seule avec le compte, lecture des positions, journal complet. Si le résultat est incertain (réponse perdue), la commande te le dit et **ne renvoie jamais** : tu vérifies le terminal d'abord.

## Procédure

Prérequis : terminal MetaTrader 5 ouvert, connecté au compte démo, marché ouvert, aucune annonce américaine proche (voir `python -m trading_pro.cli us-events`).

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
```

1. **Allumer « Trading algo »** dans la barre d'outils de MetaTrader 5 (ou Ctrl+E). C'est ton geste : l'application ne le fait pas.
2. **Lever l'arrêt des entrées** (une seule tentative sera possible ensuite) :
   ```powershell
   python -m trading_pro.cli kill-switch release --confirm "LEVER L'ARRET DES ENTREES" --reason "premier ordre demo supervise"
   ```
3. **Envoyer l'ordre minimal** (exemple : achat sur l'or ; la commission et le glissement sont **tes hypothèses**, 0 si le courtier n'en facture pas) :
   ```powershell
   python -m trading_pro.cli mt5-send-demo XAUUSD --side BUY --confirm "ENVOYER UN ORDRE DEMO BUY XAUUSD" --commission 0 --slippage-ticks 2
   ```
   Pour un indice synthétique, ajouter `--select` si le symbole n'est pas dans la liste de surveillance, et `--max-spread` avec une valeur que tu choisis : l'écart de Volatility 75 (13,70) dépasse la limite par défaut du moteur de risque. Boom et Crash exigent au moins 0,2 lot ; le moteur peut refuser si le risque par trade est trop bas pour ce volume (`--risk-fraction`, 0,02 au maximum).
4. **Lire le rapport** : état de l'intention (`accepted` attendu), résultat du courtier, rapprochement (`deals_observed` attendu), position ouverte avec stop et objectif.
5. **Fermer la position** (ou laisser le stop ou l'objectif agir) :
   ```powershell
   python -m trading_pro.cli mt5-close-demo XAUUSD --confirm "FERMER LA POSITION DEMO XAUUSD"
   ```
   La fermeture ne concerne que les positions de ce projet (numéro magique) et fonctionne même quand l'arrêt est actif. Tu peux aussi fermer à la main dans le terminal.
6. **Éteindre « Trading algo »** quand tu as fini.

## Si ça se passe mal
- **Refus avant envoi** (phrase, fenêtre d'annonce, arrêt actif, « Trading algo » éteint, position ouverte, moteur de risque, courtier) : aucun ordre n'est parti ; le message dit pourquoi. Il faut relever l'arrêt à nouveau pour réessayer.
- **Résultat incertain** : ne pas relancer. Regarder le terminal (positions et historique), puis voir `GET /orders/intents` ou la rubrique Gestion des risques.
- **Position coincée** : la fermer à la main dans le terminal ; tout est de toute façon sur un compte démo.
- **À tout moment** : `python -m trading_pro.cli kill-switch activate` réarme l'arrêt.

## Ce que ce test ne prouve pas
Qu'un signal de stratégie soit bon (il n'y en a pas), que l'exécution tienne sous une charge continue, que le programme d'exécution durable, l'arrêt d'urgence relié, les alertes et la restauration des sauvegardes soient prêts : ces conditions de la démo de 14 jours restent ouvertes (voir `RAPPORT_ETAT.md`).
