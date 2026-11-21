# TRADING INTELLIGENCE PRO

Application de recherche XAUUSD en cours de développement. **Aucun trading réel n'est activé.** L'API démarre en observation et l'arrêt des entrées est actif par défaut. Le connecteur MT5 est une bibliothèque non branchée au serveur public. Pour comprendre chaque écran et les étapes restantes, lire le [guide utilisateur](docs/GUIDE_UTILISATEUR.md). Les liens officiels pour obtenir les accès sont dans [ACCES_API.md](docs/ACCES_API.md).

Les clés se renseignent dans [`.env.local`](.env.local) à la racine. Le fichier reste local et n'est pas suivi par Git. Ne pas copier de clé dans le frontend ou dans une conversation.

## Démarrage local

Pour l'aperçu local, seul Python 3.11+ est nécessaire. Ouvrir le dossier `C:\Users\imdad\TRADING bot pro` dans VS Code. Dans son terminal PowerShell :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro'
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-Local.ps1
```

Le script crée une clé opérateur temporaire et démarre le serveur local, qui héberge à la fois l'interface et le pilote automatique, à `http://127.0.0.1:8000`. La clé est affichée dans le terminal pour les réglages, les boutons et l'arrêt d'urgence ; elle n'est pas enregistrée. Garder le terminal ouvert (et MetaTrader 5 ouvert) ; Ctrl+C arrête le serveur. Options : `-Verify` lance d'abord toutes les vérifications, `-WithExamples` charge des données d'exemple fictives. Pour vérifier sans démarrer : `Verify-Local.ps1`. L'option de politique d'exécution ne s'applique qu'au processus lancé, sans modifier les paramètres permanents de Windows. Mode d'emploi du pilote : [docs/PILOTE_AUTOMATIQUE.md](docs/PILOTE_AUTOMATIQUE.md).

Le noyau local et l'API d'observation se lancent sans installation réseau :

```powershell
python scripts/generate_skills.py
python scripts/make_fixture.py
cd backend
python -m trading_pro.cli --database data/trading.db import-candles ..\examples\synthetic_xauusd.csv
python -m trading_pro.cli --database data/trading.db import-news ..\examples\synthetic_news.json
python -m trading_pro.cli --database data/trading.db cycle ..\examples\synthetic_xauusd.csv
python -m trading_pro.cli --database data/trading.db backtest ..\examples\synthetic_xauusd.csv
python -m trading_pro.cli --database data/trading.db evaluate ..\examples\synthetic_xauusd.csv
python -m trading_pro.cli fetch-deriv-candles R_75 data\r75_1m.csv --count 7000   # historique PUBLIC Deriv, sans compte, une requête
python -m trading_pro.cli analyze-with-models ..\examples\synthetic_xauusd.csv --model NOM_DU_MODELE   # APPEL FACTURE : exige cle et tarifs dans .env.local, voir docs/ACCES_API.md
python -m trading_pro.cli mt5-status   # LECTURE SEULE du compte MT5 demo et des contrats ; aucun ordre ; voir docs/ACCES_API.md
python -m trading_pro.cli us-events   # prochaines annonces americaines et fenetres de prudence ; voir docs/ANNONCES_US.md
python -m trading_pro.cli fetch-mt5-candles XAUUSD data\xauusd_m5.csv --timeframe M5 --count 5000   # LECTURE SEULE : vraies bougies du compte demo avec ecart reel
python -m trading_pro.cli mt5-dry-run XAUUSD   # le courtier VALIDE un ordre minimal (order_check) ; rien n'est execute
python -m trading_pro.cli evaluate-rules data\boom500_m5.csv --family boom --stop-fill spike_gap   # teste des regles contre le hasard ; voir docs/INDICES_SYNTHETIQUES.md
# Ordre demo SUPERVISE (lance par une personne, jamais par le programme) : voir docs/ORDRE_DEMO_SUPERVISE.md
python -m trading_pro.cli analyze-synthetic ..\examples\synthetic_xauusd.csv --family other   # statistiques descriptives hors ligne, voir docs/INDICES_SYNTHETIQUES.md
python -m trading_pro.cli --database data/trading.db backup data/trading-backup.db
python -m trading_pro.cli verify-backup data/trading-backup.db
$env:TIP_OPERATOR_KEY = 'une-cle-locale-longue-a-generer'
python -m trading_pro.server
```

Ouvrir **http://127.0.0.1:8000** : c'est l'interface (sans npm ni dépendance). Elle affiche les douze rubriques, le pilote automatique, les instruments, les décisions, les ordres démo, les coûts, les réglages et l'arrêt d'urgence. Le serveur écoute seulement sur l'ordinateur local.
Les étapes de vérification visuelle et fonctionnelle figurent dans [docs/REVUE_LOCALE.md](docs/REVUE_LOCALE.md).

Le journal des signaux peut être exporté sur la route authentifiée `GET /export/signals.csv`. Les ordres automatiques ne partent que sur le **compte démo** et seulement après activation volontaire (bouton, clé opérateur et phrase de confirmation) ; l'interface n'envoie jamais d'ordre elle-même.

Avec les dépendances disponibles, l'API FastAPI est une option : `python -m pip install -e ./backend` depuis la racine, puis `python -m uvicorn trading_pro.api:app --reload` depuis `backend`.

La documentation interactive `/docs` n'existe que pour l'adaptateur FastAPI ; les routes communes sont décrites dans [docs/API.md](docs/API.md). Seules les origines locales sont permises.

## Vérification

```powershell
cd backend
python -m unittest discover -s tests -v
cd ..
node scripts/test_preview_navigation.cjs
```

## Sécurité et état réel

La démonstration hors ligne `DemoBroker` simule des réponses ; elle n'est pas un compte démo MT5. `MT5DemoBroker` vérifie le mode DEMO avant preflight et immédiatement avant envoi, mais n'est pas activé par l'API. Un signal WAIT, non validé ou expiré ne déclenche aucun envoi. Les intentions d'ordre sont réservées en SQLite ; tout timeout passe à l'état `uncertain` et exige une réconciliation manuelle ou automatique avant une nouvelle tentative. Ne fournir aucun secret au navigateur ni aux agents.

Les pages de l'interface lisent les résultats locaux. Le pilote lit en direct les bougies du compte démo MetaTrader et interroge un fournisseur de modèles IA quand il est activé ; aucun fournisseur d'actualités n'est automatisé ; la période expérimentale de 14 jours n'a pas démarré. Les seuils initiaux nécessitent validation sur le contrat du courtier. Les jeux d'exemple sont **synthétiques** et leurs profits simulés ne prédisent aucun résultat. Les indices synthétiques (Volatility, Boom/Crash, Step, Jump, Range Break) sont une famille distincte de XAUUSD, étudiée hors ligne seulement : voir [indices synthétiques](docs/INDICES_SYNTHETIQUES.md). Voir [avancement](docs/AVANCEMENT.md), [architecture](docs/ARCHITECTURE.md), [intégrations](docs/INTEGRATIONS.md) et [runbook](docs/RUNBOOK.md).

## Déploiement prévu

Cible du cahier des charges : Railway (API, workers, PostgreSQL, Redis) et un VPS Windows (terminal MT5 et connecteur sortant). Aujourd'hui tout tourne sur l'ordinateur de l'utilisateur. Les fichiers de production, l'authentification forte et la réconciliation sont à réaliser et valider avant tout déploiement. Aucun service payant n'a été commandé.
