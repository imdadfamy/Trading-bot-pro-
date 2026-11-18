param()
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$previousLocation = Get-Location
try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'Python 3.11+ est nécessaire pour vérifier le projet.'
    }
    Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Les tests Python ont échoué.' }
    python -m compileall -q trading_pro
    if ($LASTEXITCODE -ne 0) { throw 'La compilation Python a échoué.' }
    if (Get-Command node -ErrorAction SilentlyContinue) {
        Set-Location -LiteralPath $projectRoot
        node --check web/preview/preview.js
        if ($LASTEXITCODE -ne 0) { throw "Le JavaScript de l'interface locale a échoué." }
        node scripts/test_preview_navigation.cjs
        if ($LASTEXITCODE -ne 0) { throw "Le test de navigation de l'interface locale a échoué." }
    }
    $webDirectory = Join-Path $projectRoot 'web'
    if ((Get-Command npm -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath (Join-Path $webDirectory 'node_modules'))) {
        Set-Location -LiteralPath $webDirectory
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Le build Next.js a échoué.' }
    }
    else {
        Write-Host 'Build Next.js ignoré : exécuter npm install dans web pour l''inclure.' -ForegroundColor Yellow
    }
    Write-Host 'Vérifications locales réussies. Aucune connexion MT5 ni ordre envoyé.' -ForegroundColor Green
}
finally {
    Set-Location -LiteralPath $previousLocation.Path
}
