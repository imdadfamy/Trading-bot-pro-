# Guide de lecture et de démarrage

## Ouvrir le bon projet

Le projet est dans `C:\Users\imdad\TRADING bot pro`. Dans VS Code, utiliser **Fichier > Ouvrir un dossier** et sélectionner ce dossier. Le chemin affiché après `PS` dans le terminal est le répertoire courant : il peut être différent si VS Code a ouvert un dossier `Documents\Codex\...`.

Dans un terminal PowerShell, exécuter les deux lignes suivantes :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro'
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-Local.ps1
```

`powershell` est fourni par Windows. `pwsh` désigne PowerShell 7, facultatif, qui peut ne pas être installé. L'option `ExecutionPolicy Bypass` s'applique uniquement au nouveau processus démarré pour le script. Le script lance les contrôles, importe un petit jeu artificiel, affiche une clé temporaire et sert l'interface sur `http://127.0.0.1:8000`. Laisser le terminal ouvert ; `Ctrl+C` arrête le serveur. Si le port est occupé, ajouter `-Port 8001` après le nom du script.

## Comprendre l'écran

| Rubrique | Ce qui apparaît aujourd'hui | Ce qui attend les connexions et la recette |
| --- | --- | --- |
| Vue d'ensemble | Historique local, journal, état d'observation | Capital, equity et cours temps réel du compte démo |
| Agents IA | Rapports locaux de recherche, ou liste vide | Modèles IA configurés et orchestration continue |
| Compétences | Catalogue de spécifications versionnées (27 prévues, plus 7 pour les indices synthétiques) | Implémentation et validation de chaque méthode |
| Actualités et marché | Articles et calendrier importés localement, éventuellement synthétiques | Sources mondiales autorisées et suivi continu |
| Journal des signaux | Décisions de recherche, souvent `WAIT` | Fills et positions réconciliés avec MT5 démo |
| Sessions | Horaires calculés à titre indicatif | Horaires et fuseau confirmés par le courtier |
| Backtests | Diagnostic sur données artificielles | Historique licencié et coûts réalistes validés |
| Mémoire collective | Observations stockées lors des cycles | Évaluation et apprentissage contrôlé dans le temps |
| Gestion des risques | Mode observation, arrêt des entrées et nombre d'intentions à rapprocher | Contrôles de bout en bout avec passerelle démo |
| Intégrations | Liste des conditions bloquant les 14 jours | Preuves vérifiées pour chaque condition |
| Budget IA | Plafonds et appels enregistrés | Tarifs et facturation des fournisseurs raccordés |
| Paramètres | Modèles et plafonds versionnés, protégés par clé locale | Gestion des accès, MFA et coffre de secrets |

**Historique local** ne veut pas dire **flux direct**. Les résultats du fichier `examples/synthetic_xauusd.csv` sont artificiels. Un graphique ou un résultat de backtest n'atteste pas de profits réalisables. Un compte démo MT5 n'est pas encore raccordé. Aucun trading en argent réel n'est autorisé.

## Vérifier les réglages et l'arrêt

La clé opérateur temporaire apparaît uniquement dans la fenêtre PowerShell du serveur. Dans **Paramètres**, la saisir, charger la version actuelle, puis modifier les modèles ou les plafonds. La sauvegarde crée une nouvelle version sur le serveur ; la clé n'est pas enregistrée dans le navigateur. Un budget enregistré ne déclenche aucun appel IA. Le bouton **ARRÊT D'URGENCE** enregistre l'arrêt des nouvelles entrées dans l'API locale ; il ne prouve pas encore l'arrêt d'une passerelle MT5 externe.

Pour lancer seulement les tests, sans serveur :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro'
powershell -NoProfile -ExecutionPolicy Bypass -File .\Verify-Local.ps1
```

## Ce qui doit encore être validé avant 14 jours en démo

1. Fournir un compte **DEMO** MT5, le contrat XAUUSD du courtier, les règles de stops, les horaires et les frais. Ne jamais copier un mot de passe dans le code ou le navigateur.
2. Choisir les fournisseurs de cours, actualités, calendrier et modèles IA, leurs licences, quotas et budgets ; conserver leurs secrets côté serveur.
3. Finaliser et tester la passerelle authentifiée, la réconciliation des ordres après panne et les contrôles de risque sur le contrat réel du compte **DEMO**.
4. Pour un déploiement externe : remplacer SQLite local par un stockage partagé, ajouter une file durable, l'authentification multi-utilisateur, MFA, sauvegardes et supervision ; valider l'interface Next.js avec ses dépendances.
5. Après ces essais et les preuves de recette, décider explicitement du lancement de l'expérience de 14 jours. Les API seules ne satisfont pas ces étapes.

La liste technique détaillée est dans [INTEGRATIONS.md](INTEGRATIONS.md), [DEPLOYMENT.md](DEPLOYMENT.md) et [AVANCEMENT.md](AVANCEMENT.md).
