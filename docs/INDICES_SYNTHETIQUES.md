# Étude des indices synthétiques — 18 novembre 2026

## Sources et constat

- [Deriv, indices synthétiques](https://deriv.com/markets/derived-indices/synthetic-indices) : marchés simulés disponibles 24 h/24 ; familles Volatility, Boom/Crash, Step, Jump et Range Break. Les annonces économiques externes n'influencent pas leurs cours. Le fournisseur précise que les motifs historiques de la plupart de ces indices peuvent être fortuits et que les indicateurs techniques n'ont pas nécessairement la même pertinence que sur un marché avec carnet d'ordres.
- [Deriv, historique des ticks](https://developers.deriv.com/docs/data/ticks-history/) : l'API publique permet de demander des ticks ou des bougies historiques par symbole, sans authentification pour cet endpoint. [La liste des symboles actifs](https://developers.deriv.com/docs/data/) peut aussi être consultée. La disponibilité des instruments et leurs caractéristiques sur un compte MT5 démo sont à confirmer sur ce compte ; un historique public n'est pas une preuve des prix exécutables MT5.

## Décision pour TRADING INTELLIGENCE PRO

Les indices synthétiques forment une famille de marché distincte de XAUUSD. L'analyse fondamentale, les annonces et les sessions forex ne seront pas utilisées comme preuves directionnelles pour ces indices. Les paramètres de risque, spreads, valeurs du tick, horaires, frais et symboles doivent être relevés auprès du courtier et du compte démo avant tout backtest d'exécution. La passerelle MT5 reste désactivée et aucune famille n'est autorisée à envoyer un ordre.

Le premier outil est une **recherche statistique hors ligne** : `analyze-synthetic` prend un CSV de bougies closes d'un seul courtier et d'un seul symbole. Il calcule la dispersion par bougie, la variation médiane, la fréquence empirique des mouvements absolus dépassant un seuil choisi, un intervalle de Wilson indicatif et deux périodes chronologiques. Ces chiffres décrivent l'échantillon ; ils ne démontrent pas une régularité future. L'intervalle de Wilson suppose des observations indépendantes, hypothèse potentiellement fausse sur des séries financières. Le rapport affiche `statistically_sufficient: false` si l'échantillon comporte moins de 100 rendements ou moins de 30 dans la dernière période. Même `true` ne vaut pas validation d'une stratégie.

Exemple avec **des données réelles exportées et vérifiées** d'un seul compte démo MT5, au format CSV décrit dans `backtest.py` :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
python -m trading_pro.cli analyze-synthetic C:\chemin\vers\bougies.csv --family volatility --jump-threshold-pct 1
```

Le CSV `examples/synthetic_xauusd.csv` est un jeu **artificiel XAUUSD de tests logiciels**, pas un historique d'indices synthétiques. Ne pas l'utiliser pour conclure sur Volatility, Boom ou Crash.

## Étapes de validation avant une éventuelle extension

1. Confirmer le courtier, le compte DEMO, les symboles exacts et les spécifications des contrats sur MT5.
2. Collecter les historiques autorisés, les prix bid/ask, les heures et la fréquence des données, puis documenter trous et différences de source.
3. Préenregistrer une hypothèse mesurable par famille ; évaluer chronologiquement hors échantillon avec coûts et glissement réels, puis comparer à un témoin naïf.
4. Ne considérer une expérimentation démo automatisée qu'après recette indépendante des risques et de la réconciliation. Aucun trading réel.

## Historique public Deriv (commande `fetch-deriv-candles`)

Pour obtenir un premier échantillon sans compte, `fetch-deriv-candles` envoie **une seule requête publique, sans authentification**, au point d'accès WebSocket public de Deriv (`api.derivws.com`, aucun jeton, aucune route de trading) et enregistre les bougies **closes** dans un nouveau CSV. Le serveur renvoie au plus 1000 bougies par requête : la commande pagine vers le passé (jusqu'à 20 000 bougies), ignore la bougie en cours de formation et refuse d'écraser un fichier existant sans `--overwrite`.

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
python -m trading_pro.cli fetch-deriv-candles R_75 data\r75_1m.csv --granularity 60 --count 7000
python -m trading_pro.cli analyze-synthetic data\r75_1m.csv --family volatility --jump-threshold-pct 0.2
```

Symboles vérifiés le 18 novembre 2026 : `R_75` (Volatility 75), `BOOM500`, `CRASH500`. Granularités acceptées : 60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400 et 86400 secondes.

**Limites à garder en tête :** ces bougies publiques n'ont ni bid ni ask ; la commande copie la clôture dans `bid` et `ask` et marque le courtier `deriv-public`. Elles ne disent rien des spreads, glissements, volumes ou prix exécutables du compte MT5. Elles servent uniquement à décrire l'échantillon. Un historique récent de quelques jours ne suffit pas à conclure sur la régularité de ces marchés.

## Données réelles du compte démo MT5 (18 novembre 2026)

Les indices synthétiques existent sur le compte démo Deriv, avec le **prix acheteur et vendeur réels**, ce que l'historique public n'offre pas. Export de 5 000 bougies de 5 minutes (du 1er au 18 novembre 2026, marché ouvert 24 h sur 24, aucune pause ni week-end) :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
python -m trading_pro.cli fetch-mt5-candles "Volatility 75 Index" data\v75_m5.csv --timeframe M5 --count 5000 --select
python -m trading_pro.cli fetch-mt5-candles "Boom 500 Index" data\boom500_m5.csv --timeframe M5 --count 5000 --select
python -m trading_pro.cli fetch-mt5-candles "Crash 500 Index" data\crash500_m5.csv --timeframe M5 --count 5000 --select
python -m trading_pro.cli analyze-synthetic data\v75_m5.csv --family volatility --jump-threshold-pct 0.1 --save
```

Les noms de symboles sont ceux du terminal (avec espaces). `--select` ajoute le symbole à la liste de surveillance du terminal ; la première fois, l'outil attend quelques secondes un cours vivant pour mesurer l'horloge du serveur (décalage UTC) et refuse un cours figé. Les fichiers restent hors de Git.

| Indice | Écart médian | Écart en % du prix | Écart / mouvement moyen d'une bougie | Sauts de plus de 0,1 % |
| --- | --- | --- | --- | --- |
| Volatility 75 | 13,70 (fixe) | 0,035 % | 0,19 | 1 635 hausses, 1 657 baisses |
| Boom 500 | 0,082 | 0,0014 % | 0,02 | 757 hausses, 0 baisse |
| Crash 500 | 0,041 | 0,0014 % | 0,02 | 0 hausse, 751 baisses |

Lecture : l'écart n'écrase pas le mouvement d'une bougie de 5 minutes (de 2 % à 19 % de celui-ci), contrairement à ce qu'on pourrait craindre pour Volatility 75. L'asymétrie de Boom et Crash se confirme sur des données réelles du courtier. Les contrats relevés (volume minimal 0,2 pour Boom et Crash, stops minimaux très larges) sont dans `AVANCEMENT.md`, Décision 034. **Une seule bougie manque** (lundi 2 novembre, 13:00 UTC), commune aux trois indices : le contrôle de qualité la refuse, par prudence, tant qu'on ne l'accepte pas explicitement.

### Backtest de base sur ces données

Règle de croisement de moyennes 5 contre 20, stop de 2,5 fois la bougie médiane, objectif double, contrat réel de chaque indice (valeur du point, lots, pas), sans commission (Deriv facture le seul écart sur ces indices, à confirmer), glissement nul par hypothèse :

| Indice | Trades | Facteur de profit | Espérance | Entraînement / validation / test |
| --- | --- | --- | --- | --- |
| Volatility 75 | 112 | 1,07 | +0,04 R | 1,35 / 1,07 / 0,63 |
| Boom 500 | 253 | 1,02 | +0,02 R | 1,16 / 0,99 / 0,77 |
| Crash 500 | 258 | 1,10 | +0,07 R | 1,13 / 1,14 / 0,94 |

**À ne pas sur-interpréter.** Les facteurs de profit sont proches de 1 et l'écart avec le hasard est faible : avec 112 à 258 trades, l'erreur statistique typique d'une espérance est d'environ 0,09 à 0,13 R, donc +0,02 à +0,07 R ne se distingue pas du hasard. Le point le plus parlant est que la période de **test**, la seule non utilisée pour choisir quoi que ce soit, est sous 1 pour les trois indices (0,63, 0,77, 0,94) : le léger avantage de la première partie s'efface. Ces marchés sont engendrés par un générateur aléatoire ; une règle de croisement n'a aucune raison d'y trouver une structure, ce que ces chiffres confirment. Échantillon : 17 jours.
