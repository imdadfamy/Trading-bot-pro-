# Agents automatiques (mode observation)

**À quoi ça sert.** Les agents analysent chaque nouvelle bougie sur Volatility 10, Boom 500, Crash 500, Drift Switch 10/20/30 (lus en M1) et l'or (M5), jour et nuit, tant que tu ne les désactives pas. Ils **n'envoient aucun ordre**. Chaque avis est journalisé ; chaque achat ou vente ouvre une **position simulée** mesurée sur les vraies bougies suivantes (écart d'achat-vente inclus). C'est ainsi qu'on apprend quelles méthodes, quelles compétences et quelles sessions donnent de bonnes analyses.

## Utilisation
1. Lance l'application : **double-clique sur `Lancer-Application.bat`** (ou, dans PowerShell, `.\Start-Local.ps1` : le `.\` est obligatoire) : le serveur local héberge le pilote. La clé opérateur s'affiche dans sa fenêtre PowerShell. Le démarrage est rapide : les vérifications complètes (`-Verify`) et les données d'exemple fictives (`-WithExamples`) sont désormais facultatives, et le lanceur ne régénère plus les compétences.
2. Vue d'ensemble → **Activer les agents** → saisis la clé. Le mode est mémorisé : après un redémarrage du serveur, les agents reprennent seuls. **Désactiver les agents** les arrête après le cycle en cours.
3. MetaTrader 5 doit être ouvert et connecté au compte démo (lecture seule). Le bouton « Trading algo » n'est pas nécessaire.
4. Ne lance qu'**un seul** pilote à la fois (serveur ou commande `autopilot once`), sinon deux processus initialisent MetaTrader en même temps.

## Ce qui est comparé (« méthodes »)
| Méthode | Contenu |
|---|---|
| Règle simple | croisement de moyennes 5/20 (référence du cahier des charges) |
| Analyste de base | tendance 5/20 sans IA |
| Agents IA sans compétences | analyste graphique, quantitatif, veilleur (or seulement), directeur par accord de deux analystes |
| Agents IA + compétences | mêmes agents, avec indicateurs calculés par code (ATR, RSI, dérive, pics, swings, fourchette, volume) et 3 compétences tirées au sort à chaque cycle |
| Agents IA + compétences, direction forcée | mêmes données, mais l'analyste doit choisir achat ou vente ; comparé au pile ou face |
| Pile ou face | achat ou vente tiré au hasard à chaque cycle : la référence du hasard |
| **Directeur IA** (`ai:director`) | une IA qui lit **tous les rapports** de la consultation (analystes, règles de base, coût en R, indicateurs, annonces) et tranche ; pour l'or et les Drift Switch seulement, elle voit aussi les 4 consultations précédentes (votes et prix) pour vérifier qu'une dérive persiste. Elle ignore l'historique sur Boom, Crash et Volatility (sans mémoire). Comparée au directeur par vote et au pile ou face ; n'est pas l'ordre par défaut |

Pour chaque méthode : nombre de positions, R moyen (gain ou perte en multiple du risque initial), réussite, abstention, appels IA en échec. Rien n'est dit « significatif » sans 30 positions au moins et un intervalle corrigé au-dessus de zéro. Les écarts avec/sans compétences sont calculés par agent et par compétence (écran « Agents IA »), les résultats par session dans « Sessions ».

## Réglages (Paramètres)
- **Niveau de risque** (versionné, auteur journalisé) : risque par position, perte maximale par jour, risque cumulé, positions simultanées, écart maximal, lot fixe, commission, glissement. Appliqué aux prochains ordres démo. Valeurs du cahier des charges : 0,5 % / 2 % / 1 % / 2 positions.
- **Budget IA** : case « Limiter le budget IA ». Décochée = aucun arrêt faute de budget (réglage actuel) ; la dépense reste affichée au Budget IA. Un cycle coûte environ 0,016 $.
- **Agents automatiques** : instruments, durée des bougies, cadence de l'IA (30 min par défaut), durée maximale et distances des positions simulées, nombre de compétences par analyste.

## Commandes utiles
```powershell
python -m trading_pro.cli autopilot status
python -m trading_pro.cli autopilot performance
python -m trading_pro.cli autopilot once --symbol XAUUSD
```

## Limites connues
- Les compétences ont été enrichies le 19 novembre 2026 (sources, mesures, règles de décision : voir `INDICES_SYNTHETIQUES.md`) ; leur effet mesuré dira lesquelles aident. Aucune méthode à rentabilité démontrée n'existe dans les sources lues : les compétences enseignent surtout à mesurer et à s'abstenir.
- Les modèles répondent surtout « attente ». Pour ne pas dépendre des rares positions simulées, chaque cycle d'analyse (un par intervalle de consultation de l'IA) attribue en plus à **chaque** avis d'achat ou de vente une **note de direction à horizon fixe** : mouvement du prix après un délai égal à cet intervalle, en distances de stop et après l'écart d'achat-vente, sans position bloquée ni chevauchement. Les écrans « Agents IA » (carte « Qualité de la direction à horizon fixe » et comparaison avec le pile ou face) s'appuient dessus. Il faut quand même des jours pour conclure.
- Un symbole tout juste ajouté à MetaTrader répond d'abord avec d'anciennes bougies : la première lecture est redemandée quelques fois (environ dix secondes) ; si les données restent périmées, l'indice synthétique (ouvert 24 h sur 24) est relu après une minute, l'or après cinq.
- L'or est fermé la nuit et le week-end (données périmées ignorées) ; les annonces américaines suspendent l'analyse de l'or, pas celle des indices synthétiques.
- Les **ordres automatiques en démo** (étape 3) ne sont pas encore branchés : le mode `demo_auto` est refusé.

## Ordres automatiques en démo (étape 3)
**Activation.** Vue d'ensemble → « Activer les ordres automatiques en démo » → clé opérateur **et** phrase `ACTIVER LES ORDRES AUTOMATIQUES DEMO` (vérifiée par le serveur). Activer lève l'arrêt des nouvelles entrées ; repasser en observation ou désactiver le remet. Le bouton **ARRÊT D'URGENCE** bloque aussitôt toute nouvelle entrée ; les positions ouvertes gardent leur stop et leur objectif chez le courtier et restent suivies. Un redémarrage du serveur reprend dans le dernier mode (ordres compris) : vérifie l'état affiché.

**Qui décide.** Les méthodes listées dans Paramètres → « Méthodes dont les avis deviennent des ordres démo » (par défaut `skills:director` : deux analystes IA d'accord, avec compétences). Le premier avis d'achat ou de vente de la liste, à chaque nouvelle bougie, tente un ordre. Les avis forcés ou la règle simple peuvent y être ajoutés pour accumuler des ordres ; ils n'ont aucun avantage démontré.

**Garde-fous, dans l'ordre** (chacun refuse sans rien envoyer et journalise la raison) : arrêt des entrées ; une seule tentative par décision (jamais de renvoi) ; fenêtre d'annonce américaine pour l'or (calendrier strict) ; compte DÉMO ; « Trading algo » allumé (ton geste, jamais touché par le programme) ; cotation de moins de 15 s ; aucune position du projet déjà ouverte sur l'instrument ; moteur de risque avec le vrai capital, la perte du jour mesurée sur l'historique du compte, le risque ouvert réel, le nombre de positions et la limite d'écart (0 = automatique : 10 % du stop) ; stop au moins égal à 1,5 fois le minimum du courtier ; vérification du courtier (`order_check`) juste avant l'envoi. Volume : calculé d'après le risque, ou lot fixe des paramètres s'il tient dans la capacité de risque.

**Après l'envoi.** Stop et objectif vérifiés chez le courtier : une position sans protection est fermée aussitôt, l'arrêt des entrées s'active et une alerte est levée. Un résultat incertain active l'arrêt des entrées, lève une alerte et n'est jamais renvoyé. Une position qui dépasse l'horizon de la stratégie (comme son jumeau simulé) est fermée au marché. Chaque position fermée est enregistrée avec son résultat net (frais compris) et la raison de sortie ; tout est relié à une décision et à un signal journalisés (écran « Journal des signaux »).

**Ce que cela ne fait pas.** Pas d'alerte hors de l'application (aucun Telegram branché : les alertes sont dans la base et le journal), pas de pilote hébergé hors de ton ordinateur (le serveur local doit tourner et MetaTrader rester ouvert), pas d'argent réel. Les conditions formelles de l'expérience de 14 jours (restauration de sauvegarde testée, alertes externes, stratégie figée, licence des actualités) restent à remplir.

## Dimensionnement par instrument (stop et lot)
Un point ne vaut pas la même chose partout : pour un lot, un mouvement d'une unité de prix rapporte **1 $ sur chaque indice synthétique** et **100 $ sur l'or**. Un lot de 0,2 sur Boom ne risque donc presque rien comparé à 0,2 lot d'or. Le programme ne refuse donc **plus aucun instrument à cause de son lot ou de son échelle** : il adapte le stop, puis calcule le lot d'après l'argent risqué.

- **Stop** = le plus grand de : le stop de volatilité (2 fois l'ATR), **dix fois l'écart d'achat-vente** (le coût reste sous 0,1 R) et, sur Boom et Crash, le **pic typique** (90e centile mesuré, sinon 0,2 % du prix) : un stop plus serré est simplement sauté. Au moins 1,5 fois le minimum du courtier.
- **Lot** = argent risqué (0,5 % du capital par défaut, réglable) divisé par le stop en argent. Du côté où un pic joue contre la position (vente sur Boom, achat sur Crash), on dimensionne comme si un demi-stop de plus pouvait être perdu.
- **Valeurs réelles du 21 novembre 2026** (capital 10 000 $, 0,5 % = 50 $) : Volatility 10 stop 4,6 et lot 10,9 ; Boom 500 stop 11,3 et lot 4,4 ; Crash 500 stop 5,5 et lot 9,0 ; Drift Switch 10 stop 7,8 et lot 6,4 ; Drift Switch 20 stop 7,9 et lot 6,3 ; Drift Switch 30 stop 66,7 et lot 0,74 (écart de 10 % du stop : l'indice le plus coûteux). Le courtier a validé un ordre minimal d'achat et de vente sur les sept instruments (vérification sans envoi).
- Le même stop sert à la position simulée et à l'ordre réel : leurs résultats restent comparables.

## Suivi des positions et signaux contraires
**Panneau « Positions ouvertes »** (Vue d'ensemble, sous la carte du pilote) : pour chaque position, l'instrument, le sens et le lot, la méthode qui l'a décidée, le cours actuel, le **résultat en cours** (lu chez le courtier toutes les 10 secondes), le stop et l'objectif, le temps restant avant la fermeture automatique, et le total en cours. Le bouton **Fermer toutes les positions** (clé opérateur et phrase `FERMER TOUTES LES POSITIONS DEMO`) ferme au prix du marché les positions du projet (jamais celles ouvertes à la main) puis active l'arrêt des nouvelles entrées ; « Reprendre les ordres » le lève.

**Une seule position par instrument.** Le pilote n'ouvre jamais une deuxième position sur un instrument déjà occupé : pas de cumul dans le même sens, pas de position inverse en même temps (pas de couverture ni d'inversion aveugle, comme l'exige le cahier des charges).

**Signal contraire pendant qu'une position est ouverte.** Si une méthode d'exécution annonce le sens opposé (par exemple vente alors qu'un achat est ouvert), le pilote l'enregistre, l'affiche sur la position (bandeau « Signal contraire reçu ») et dans le fil d'activité, puis applique la règle choisie dans Paramètres (`opposite_signal_policy`) :
- `ignore` (par défaut) : la position garde son stop et son objectif ; ainsi la position réelle reste comparable à sa jumelle simulée ;
- `close_if_profit` : la position est fermée au marché **seulement si elle est en gain** (jamais une position perdante n'est fermée avant son stop) ;
- `close` : la position est fermée.
Dans tous les cas l'ordre inverse n'est pas ouvert en même temps ; si le signal persiste, il passe ensuite par tous les garde-fous comme un ordre ordinaire une fois la position partie. La fermeture sur signal contraire reste possible quand l'arrêt d'urgence est actif (elle ne fait que réduire le risque). Fermer plus tôt un gain coupe aussi les gains qui auraient continué : aucune preuve ne dit quelle règle est la meilleure, c'est ce que la mesure dira.
