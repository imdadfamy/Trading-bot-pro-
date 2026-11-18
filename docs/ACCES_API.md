# Obtenir les accès pour TRADING INTELLIGENCE PRO

Les liens ci-dessous pointent vers les sites officiels. Vérifier le tarif, la licence et les limites avant toute souscription. **Ne coller aucune clé dans l'interface publique, dans Git ou dans une conversation.** Les secrets seront configurés côté serveur après choix des services.

| Besoin | Où obtenir l'accès | Variable locale prévue | État du code |
| --- | --- | --- | --- |
| Compte de trading DEMO XAUUSD | [MetaTrader 5 : ouvrir un compte démo](https://www.metatrader5.com/en/terminal/help/startworking/acc_open), puis choisir un courtier offrant XAUUSD sur MT5 | `TIP_MT5_DEMO_LOGIN`, `TIP_MT5_DEMO_SERVER` ; mot de passe dans un coffre, jamais dans le dépôt | Bibliothèque MT5 désactivée ; passerelle et recette du courtier restent à terminer |
| Modèles IA | [Créer une clé API OpenAI](https://platform.openai.com/api-keys), [documentation des clés](https://developers.openai.com/api/docs/guides/api-keys) | `OPENAI_API_KEY` | Adaptateur, prompts figés et commande `analyze-with-models` disponibles ; un essai réel plafonné a réussi ; aucune exécution continue ni évaluation de qualité |
| Articles mondiaux pour la recherche | [Obtenir une clé NewsAPI](https://newsapi.org/register), [documentation](https://newsapi.org/docs/authentication) | `TIP_NEWSAPI_KEY` | Un appel manuel et import d'articles non confirmés sont préparés |
| Calendrier économique mondial | [Portail développeur Trading Economics](https://developer.tradingeconomics.com/), [documentation](https://docs.tradingeconomics.com/get_started/) | `TIP_TRADING_ECONOMICS_KEY` | Import manuel du calendrier américain disponible ; abonnement et suivi continu à valider |
| Données intermarket supplémentaires, facultatives | [Twelve Data : compte et clé](https://twelvedata.com/docs/introduction/libraries) | À définir après choix du périmètre et des symboles | Non intégré ; les cours XAUUSD doivent d'abord venir du même courtier MT5 que l'exécution |

## Ordre recommandé

1. **Compte MT5 DEMO** : relever nom du courtier, nom exact du serveur, identifiant du compte, nom exact du symbole XAUUSD et caractéristiques du contrat. MetaTrader n'est pas le courtier et ne fournit pas les identifiants du compte de trading à sa place.
2. **OpenAI API** : créer un projet distinct et fixer un budget. L'abonnement ChatGPT et la facturation de l'API sont séparés. Ne pas choisir un modèle ou un prix au hasard : relever ses tarifs d'entrée et de sortie, puis configurer les plafonds dans l'application.
3. **Actualités** : pour vérifier le logiciel, une clé de développement NewsAPI peut suffire. Le plan développeur a un délai de 24 heures pour les articles et est réservé au développement ; il ne répond donc pas au besoin de veille réellement immédiate. Vérifier les droits et coûts du plan de production avant achat.
4. **Calendrier** : Trading Economics propose des données économiques et des événements ; vérifier la couverture, la précision des heures, les quotas et le tarif adapté au projet avant souscription. Aucune souscription n'est effectuée automatiquement.

## Où placer les clés

Pour les agents IA, renseigner aussi `TIP_OPENAI_INPUT_USD_PER_M` et `TIP_OPENAI_OUTPUT_USD_PER_M` (prix en dollars par million de jetons, **copiés depuis la grille tarifaire officielle du modèle choisi**). Aucun tarif n'est supposé : sans ces deux valeurs, `analyze-with-models` refuse de démarrer, sans appel réseau.

Ouvrir [`.env.local`](../.env.local) à la racine du projet et remplir les valeurs après `=`. Le fichier est ignoré par Git et lu automatiquement au lancement de l'API locale, de l'adaptateur FastAPI et de la CLI. Les variables déjà définies dans le processus ont priorité. Ne jamais placer ces valeurs dans `web/.env.local`, dans une variable `NEXT_PUBLIC_*` ou dans un message. `Start-Local.ps1` génère sa propre clé opérateur temporaire.

## Essai local après avoir renseigné `.env.local`

Dans le terminal PowerShell courant, après avoir obtenu une clé **NewsAPI** et uniquement pour un appel volontaire :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
python -m trading_pro.cli --database data/trading.db poll-newsapi
```

Cette commande importe des titres comme événements **non confirmés**, sans attribution automatique à XAUUSD et sans envoi d'ordre. Ne pas lancer cette commande avec une clé de développement en pensant obtenir du temps réel. L'état `/readiness` affiche seulement si des accès sont renseignés, jamais leur valeur ; il reste bloqué pour les 14 jours tant que les connexions et les essais du compte démo ne sont pas validés.

La commande `python -m trading_pro.cli --database data/trading.db poll-calendar` lit une fois le calendrier américain via `TIP_TRADING_ECONOMICS_KEY`, si son contrat le permet. Elle conserve les versions reçues pour éviter de réécrire le passé ; elle ne lance aucun ordre ni surveillance continue.

## Analyse assistée par modèles (appel facturé, explicite)

Après avoir renseigné la clé et les deux tarifs, choisi un modèle par agent dans **Paramètres** (ou `--model`) et fixé des plafonds modestes :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
python -m trading_pro.cli --database data/trading.db analyze-with-models ..\examples\synthetic_xauusd.csv --model NOM_DU_MODELE --max-call-usd 0.05
```

La commande lance au plus un appel par agent choisi (`graph`, `news`, `quant`), chacun borné par le plafond par appel, le plafond quotidien et le plafond de l'expérience. Elle ne lance aucun ordre. Configurer aussi un plafond de dépense côté OpenAI : le plafond local n'est pas une garantie de facturation.

## Contrôle du compte MT5 démo (lecture seule)

Prérequis : le paquet `MetaTrader5` (`python -m pip install MetaTrader5==5.0.6231`), le terminal MetaTrader 5 installé, et `TIP_MT5_DEMO_LOGIN`, `TIP_MT5_DEMO_SERVER` (et au besoin `TIP_MT5_DEMO_PASSWORD`) dans `.env.local`.

**Aucune saisie manuelle n'est nécessaire** : la commande se connecte au terminal avec `TIP_MT5_DEMO_LOGIN`, `TIP_MT5_DEMO_SERVER` et `TIP_MT5_DEMO_PASSWORD` du `.env.local`, par l'API officielle (le mot de passe va à MetaTrader seulement). Un terminal qui démarre sans compte enregistré affiche une fenêtre « Se connecter » ou « Ouvrir un compte » : cette fenêtre l'empêche de répondre à l'application (erreur `-10005`, délai). Il suffit de la **fermer sans rien saisir**, puis de relancer la commande. Après la première connexion réussie, le terminal garde le compte.

L'algo-trading du terminal (bouton « Trading algo » de la barre d'outils) est **désactivé par défaut** ; il n'est nécessaire que pour envoyer des ordres, jamais pour cette lecture.

Puis :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
python -m trading_pro.cli mt5-status
```

La commande refuse tout compte qui n'est pas **DEMO**, n'appelle aucune fonction de trading (elle est protégée par une liste de fonctions autorisées), masque l'identifiant, n'affiche jamais le mot de passe et liste XAUUSD et les indices synthétiques avec leur contrat (lot, tick, volume, écart, niveau de stops, modes d'exécution). `--select` ajoute les symboles trouvés à la liste de surveillance du terminal pour lire un cours.
