# Agents automatiques (mode observation)

**À quoi ça sert.** Les agents analysent chaque nouvelle bougie M5 sur Volatility 75 et sur l'or, jour et nuit, tant que tu ne les désactives pas. Ils **n'envoient aucun ordre**. Chaque avis est journalisé ; chaque achat ou vente ouvre une **position simulée** mesurée sur les vraies bougies suivantes (écart d'achat-vente inclus). C'est ainsi qu'on apprend quelles méthodes, quelles compétences et quelles sessions donnent de bonnes analyses.

## Utilisation
1. Lance l'application (`Start-Local.ps1`) : le serveur local héberge le pilote. La clé opérateur s'affiche dans sa fenêtre PowerShell.
2. Vue d'ensemble → **Activer les agents** → saisis la clé. Le mode est mémorisé : après un redémarrage du serveur, les agents reprennent seuls. **Désactiver les agents** les arrête après le cycle en cours.
3. MetaTrader 5 doit être ouvert et connecté au compte démo (lecture seule). Le bouton « Trading algo » n'est pas nécessaire.
4. Ne lance qu'**un seul** pilote à la fois (serveur ou commande `autopilot once`), sinon deux processus initialisent MetaTrader en même temps.

## Ce qui est comparé (« méthodes »)
| Méthode | Contenu |
|---|---|
| Règle simple | croisement de moyennes 5/20 (référence du cahier des charges) |
| Analyste de base | tendance 5/20 sans IA |
| Agents IA sans compétences | analyste graphique, quantitatif, veilleur (or seulement), directeur par accord de deux analystes |
| Agents IA + compétences | mêmes agents, avec indicateurs calculés par code (ATR, swings, fourchette, volume) et 3 compétences tirées au sort à chaque cycle |

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
- Les modèles répondent surtout « attente » : les premières heures donneront peu de positions mesurées ; il faut des jours pour conclure.
- L'or est fermé la nuit et le week-end (données périmées ignorées) ; les annonces américaines suspendent l'analyse de l'or, pas celle des indices synthétiques.
- Les **ordres automatiques en démo** (étape 3) ne sont pas encore branchés : le mode `demo_auto` est refusé.
