# Revue locale rapide

1. Depuis la racine du projet, ouvrir PowerShell et exécuter `powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-Local.ps1`.
2. Attendre « Vérifications locales réussies », puis ouvrir `http://127.0.0.1:8000` dans le navigateur du même PC.
3. Vérifier les douze rubriques : le graphique est étiqueté historique/synthétique, MT5 est déconnecté, la session est indicative et le mode est observation.
4. Dans **API & Integrations**, vérifier `ready_for_14_day_demo = Non` et la liste des prérequis. Dans **Settings**, saisir la clé temporaire affichée dans PowerShell ; charger les paramètres et modifier, par exemple, le plafond quotidien. La version doit augmenter après enregistrement.
5. Cliquer sur **ARRÊT D’URGENCE** et utiliser cette même clé ; la confirmation doit indiquer que l'arrêt des nouvelles entrées est enregistré. Ctrl+C dans PowerShell arrête ensuite le serveur.

L'interface locale permet une revue fonctionnelle, pas une démonstration de trading. Les résultats du backtest proviennent d'un fichier créé artificiellement. Aucun compte ou fournisseur externe n'est connecté. Si le port 8000 est utilisé, lancer `powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-Local.ps1 -Port 8001` puis ouvrir l'adresse affichée.
