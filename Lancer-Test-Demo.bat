@echo off
rem Double-cliquez ce fichier pour lancer le test guide d un ordre DEMO.
rem Il ouvre le script guide : rien ne part sans vos deux gestes (Trading algo + le mot ENVOYER).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Lancer-Test-Demo.ps1"
echo.
pause
