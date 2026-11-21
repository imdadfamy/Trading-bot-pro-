@echo off
rem Double-cliquez ce fichier pour lancer l application (serveur local + pilote automatique).
rem La cle operateur s affiche dans cette fenetre : gardez-la ouverte, Ctrl+C arrete le serveur.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Local.ps1"
echo.
pause
