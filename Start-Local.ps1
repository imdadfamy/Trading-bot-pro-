param(
    [ValidateRange(1,65535)][int]$Port = 8000,
    # Off by default: the example candles and headlines are fake (broker "SYNTHETIC-NOT-A-BROKER") and would mix with real data.
    [switch]$WithExamples,
    # Off by default: the full check takes minutes. Run it on purpose, or use Verify-Local.ps1 directly.
    [switch]$Verify
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$previousLocation = Get-Location
$previousKey = [Environment]::GetEnvironmentVariable('TIP_OPERATOR_KEY', 'Process')
try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'Python 3.11+ est nécessaire. Consultez le README.'
    }
    if ($Verify) { & (Join-Path $projectRoot 'Verify-Local.ps1') }
    if ($WithExamples) {
        python (Join-Path $projectRoot 'scripts/make_fixture.py')
        if ($LASTEXITCODE -ne 0) { throw "Création des données d'exemple impossible." }
    }
    Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
    if ($WithExamples) {
        python -m trading_pro.cli --database data/trading.db import-candles ../examples/synthetic_xauusd.csv
        if ($LASTEXITCODE -ne 0) { throw 'Import des bougies impossible.' }
        python -m trading_pro.cli --database data/trading.db import-news ../examples/synthetic_news.json
        if ($LASTEXITCODE -ne 0) { throw 'Import des actualités impossible.' }
    }
    $randomBytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
    $env:TIP_OPERATOR_KEY = [BitConverter]::ToString($randomBytes).Replace('-', '')
    Write-Host ''
    Write-Host "Ouvrez http://127.0.0.1:$Port dans votre navigateur." -ForegroundColor Cyan
    Write-Host "Clé opérateur temporaire : $env:TIP_OPERATOR_KEY" -ForegroundColor Yellow
    Write-Host 'Gardez cette fenêtre ouverte (le pilote automatique y tourne) et MetaTrader 5 ouvert. Ctrl+C arrête le serveur.'
    python -m trading_pro.server --database data/trading.db --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Le serveur local n'a pas démarré. Vérifiez le port et les permissions réseau." }
}
finally {
    [Environment]::SetEnvironmentVariable('TIP_OPERATOR_KEY', $previousKey, 'Process')
    Set-Location -LiteralPath $previousLocation.Path
}
