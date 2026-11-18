# Test guide d'un ordre DEMO minimal. Aucun argent reel : compte demo uniquement.
# Ce script ne fait RIEN tout seul : chaque etape attend que VOUS agissiez, et l'envoi n'a lieu
# que si VOUS tapez le mot ENVOYER.
#
# Utilisation (dans PowerShell) :
#   Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro'
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\Lancer-Test-Demo.ps1
# Pour l'or (marche ferme de 22h a 23h05 UTC et le week-end) :
#   ... -File .\Lancer-Test-Demo.ps1 -Symbol XAUUSD -MaxSpread ''
param(
    [string]$Symbol = 'Volatility 75 Index',
    [ValidateSet('BUY', 'SELL')][string]$Side = 'BUY',
    [string]$MaxSpread = '30'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$backend = Join-Path $PSScriptRoot 'backend'
$terminal = 'C:\Program Files\MetaTrader 5\terminal64.exe'
Set-Location -LiteralPath $backend

Write-Host ''
Write-Host '=== TEST GUIDE D''UN ORDRE DEMO ===' -ForegroundColor Cyan
Write-Host "Instrument : $Symbol    Sens : $Side    Volume : le plus petit autorise"
Write-Host 'Compte DEMO uniquement. Perte maximale : de l''ordre de 1 dollar fictif.'
Write-Host ''

# Etape 1 : MetaTrader doit etre ouvert
if (-not (Get-Process -Name terminal64 -ErrorAction SilentlyContinue)) {
    Write-Host 'ETAPE 1 - Ouverture de MetaTrader 5...' -ForegroundColor Yellow
    Start-Process -FilePath $terminal
    Write-Host '  Si une petite fenetre "Se connecter" ou "Ouvrir un compte" apparait : FERMEZ-LA avec la croix, sans rien saisir.'
    Read-Host '  Appuyez sur Entree quand la fenetre MetaTrader 5 est ouverte'
} else {
    Write-Host 'ETAPE 1 - MetaTrader 5 est deja ouvert. OK.' -ForegroundColor Green
}

# Etape 2 : le geste de l'utilisateur
Write-Host ''
Write-Host 'ETAPE 2 - Allumez "Trading algo" dans MetaTrader 5 (c''est VOTRE geste, le programme ne le fait pas) :' -ForegroundColor Yellow
Write-Host '  Dans la fenetre MetaTrader 5, regardez la barre de boutons en haut.'
Write-Host '  Cherchez le bouton "Trading algo". Eteint : icone rouge. Allume : icone verte (triangle).'
Write-Host '  Cliquez dessus pour le mettre au vert (ou appuyez sur Ctrl+E avec la fenetre MetaTrader au premier plan).'
Read-Host '  Appuyez sur Entree quand "Trading algo" est VERT'

# Etape 3 : confirmation finale
Write-Host ''
Write-Host 'ETAPE 3 - Confirmation' -ForegroundColor Yellow
Write-Host '  Hypotheses utilisees : commission 0 et glissement de 2 ticks (a corriger si vous connaissez les vraies valeurs).'
$answer = Read-Host '  Tapez exactement ENVOYER pour lancer l''ordre de test (autre chose = annuler, rien n''est envoye)'
if ($answer -cne 'ENVOYER') {
    Write-Host 'Annule. Rien n''a ete envoye.' -ForegroundColor Green
    exit 0
}

try {
    Write-Host ''
    Write-Host 'Levee de l''arret des entrees (une seule tentative sera possible)...'
    & python -m trading_pro.cli kill-switch release --confirm "LEVER L'ARRET DES ENTREES" --reason 'test demo supervise guide'
    if ($LASTEXITCODE -ne 0) { throw 'La levee de l''arret a echoue.' }
    Write-Host 'Envoi de l''ordre de test sur le compte DEMO...' -ForegroundColor Yellow
    $sendArgs = @('mt5-send-demo', $Symbol, '--side', $Side, '--confirm', "ENVOYER UN ORDRE DEMO $Side $Symbol",
                  '--commission', '0', '--slippage-ticks', '2', '--select')
    if ($MaxSpread -ne '') { $sendArgs += @('--max-spread', $MaxSpread) }
    & python -m trading_pro.cli @sendArgs
    $sendCode = $LASTEXITCODE
}
finally {
    & python -m trading_pro.cli kill-switch activate | Out-Null
    Write-Host ''
    Write-Host 'Arret des nouvelles entrees REACTIVE (une levee = une tentative).' -ForegroundColor Green
}

if ($sendCode -ne 0) {
    Write-Host ''
    Write-Host 'L''ordre n''a PAS ete envoye (voir le message ci-dessus). Rien n''est ouvert. Vous pouvez recommencer apres avoir corrige la cause.' -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host 'Regardez dans MetaTrader 5, onglet "Trade" en bas : la position doit apparaitre avec son stop et son objectif.' -ForegroundColor Cyan
$close = Read-Host 'Fermer la position de test maintenant ? (O pour oui, N pour la laisser ouverte)'
if ($close -match '^[oO]') {
    & python -m trading_pro.cli mt5-close-demo $Symbol --confirm "FERMER LA POSITION DEMO $Symbol"
}
Write-Host ''
Write-Host 'Pour finir, eteignez "Trading algo" (bouton redevenu rouge). Envoyez-moi ce qui s''est affiche : je verifie en lecture seule.' -ForegroundColor Cyan
