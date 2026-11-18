# Premier ordre démo supervisé

**À quoi ça sert.** Vérifier, une fois, que la chaîne complète fonctionne sur le compte démo : envoi d'un ordre minimal avec stop et objectif, retour du courtier, rapprochement, fermeture. **Ce n'est pas un test de stratégie** : l'analyse ne produit aucun signal d'achat ou de vente, l'ordre est donc forcé à la main. Le risque est de l'ordre de 1 $ sur un compte fictif.

**Qui fait quoi.** Cette procédure est lancée **par toi**. Le programme ne peut pas la déclencher seul, et l'assistant ne l'exécute pas. Chaque étape ci-dessous est une action volontaire.

## Le plus simple : le script guidé

Un script fait les étapes à ta place **sauf les deux gestes qui doivent rester les tiens** : allumer « Trading algo » et taper le mot `ENVOYER`. Il ouvre MetaTrader si besoin, te dit quoi cliquer, attend ton accord à chaque étape, réarme l'arrêt des entrées à la fin quoi qu'il arrive et propose de fermer la position.

**Le plus facile : double-clique sur `Lancer-Test-Demo.bat`** dans le dossier du projet (`C:\Users\imdad\TRADING bot pro`), depuis l'Explorateur de fichiers.

Ou, depuis n'importe quelle fenêtre de commandes (l'invite de commandes classique **ou** PowerShell), cette ligne unique avec le chemin complet fonctionne partout :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\imdad\TRADING bot pro\Lancer-Test-Demo.ps1"
```

(`Set-Location` n'existe que dans PowerShell : dans l'invite de commandes classique, il faut utiliser le chemin complet ci-dessus.)

Par défaut il utilise **Volatility 75 Index**, ouvert 24 h sur 24 (l'or est fermé de 22 h à 23 h 05 UTC et le week-end). Pour l'or : `-Symbol XAUUSD -MaxSpread ''`.

**Où cliquer pour « Trading algo ».** Dans la fenêtre MetaTrader 5, barre de boutons en haut de la fenêtre : un bouton nommé « Trading algo ». Éteint, son icône est rouge ; allumé, elle est verte (un triangle). Un clic le bascule, comme le raccourci Ctrl+E avec la fenêtre MetaTrader au premier plan. Ce réglage est celui de ton terminal : il autorise les programmes à passer des ordres, c'est pourquoi l'application ne le fait jamais à ta place.

**Où ça tourne.** Tout se passe sur ton ordinateur : le script et les commandes s'exécutent dans le dossier du projet, et MetaTrader 5 est le logiciel déjà installé chez toi. L'interface web du projet (pages sur `127.0.0.1`) **n'a aucun bouton d'envoi** : elle sert à regarder, pas à lancer un ordre.

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
