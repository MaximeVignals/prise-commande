<#
  Construit Prise de Commande (APK Android et/ou Windows).

  L'application ne contient aucun catalogue réel : chaque utilisateur importe le sien au
  premier lancement (voir FORMAT_CATALOGUE.md). Ce script construit puis copie les
  résultats dans ..\releases\.

  Version et numéro de build : pyproject.toml ([project] version, [tool.flet] build_number).
  Exemples :  .\scripts\construire.ps1            (APK + Windows)
              .\scripts\construire.ps1 -Cible apk
#>
param(
    [ValidateSet('tous', 'apk', 'windows')]
    [string]$Cible = 'tous',
    [switch]$SansOuvrir
)
$ErrorActionPreference = 'Stop'

$Depot  = Split-Path $PSScriptRoot -Parent          # ...\prise_commande\prise-commande-public
$Racine = Split-Path $Depot -Parent                 # ...\prise_commande (privé)
$Assets = Join-Path $Depot 'src\assets'

function Stop-Erreur($message) { Write-Host "`nERREUR : $message" -ForegroundColor Red; exit 1 }

# --- Vérifications ---
if (-not (Get-Command flet -ErrorAction SilentlyContinue)) {
    Stop-Erreur 'la commande "flet" est introuvable. Lancez depuis la fenêtre PowerShell habituelle (environnement Python activé).'
}
$toml = Get-Content (Join-Path $Depot 'pyproject.toml') -Raw -Encoding UTF8
$version = [regex]::Match($toml, '(?m)^version\s*=\s*"([^"]+)"').Groups[1].Value
$build   = [regex]::Match($toml, '(?m)^build_number\s*=\s*(\d+)').Groups[1].Value
if (-not $version -or -not $build) { Stop-Erreur 'version ou build_number introuvable dans pyproject.toml.' }

# Seul le catalogue fictif peut partir dans l'application
$autres = Get-ChildItem $Assets -File |
    Where-Object { $_.Extension -in '.xlsx', '.xls', '.csv', '.json' -and $_.Name -notlike 'catalogue_modele.*' }
if ($autres) { Stop-Erreur "fichier(s) de données dans src\assets : $($autres.Name -join ', '). Retirez-les avant de construire." }

if ($Cible -in 'tous', 'apk') {
    $cle = Join-Path $Racine 'signature_android\prise-commande-upload.jks'
    if (-not (Test-Path $cle)) { Stop-Erreur "clé de signature introuvable : $cle" }
    $mdp = @('signature_android\mot_de_passe.txt', 'Ne Pas Upload\mot_de_passe.txt') |
        ForEach-Object { Join-Path $Racine $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $mdp) { Stop-Erreur 'mot_de_passe.txt introuvable (signature_android\ ou Ne Pas Upload\).' }
}

Write-Host "Prise de Commande $version (build $build) - cible : $Cible" -ForegroundColor Cyan
Write-Host 'La construction prend plusieurs minutes.'

$Releases = Join-Path $Racine 'releases'
New-Item -ItemType Directory -Force $Releases | Out-Null
Push-Location $Depot
try {
    if ($Cible -in 'tous', 'apk') {
        $pass = (Get-Content $mdp -TotalCount 1).Trim()
        $env:FLET_ANDROID_SIGNING_KEY_STORE = $cle
        $env:FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD = $pass
        $env:FLET_ANDROID_SIGNING_KEY_PASSWORD = $pass
        $env:FLET_ANDROID_SIGNING_KEY_ALIAS = 'upload'
        $pass = $null
        flet build apk --yes
        if ($LASTEXITCODE -ne 0) { throw 'échec de la construction APK' }
        $apk = Get-ChildItem 'build\apk\*.apk' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        Copy-Item $apk.FullName (Join-Path $Releases "prise_commande-$version.apk") -Force
        Write-Host "APK : releases\prise_commande-$version.apk ($([math]::Round($apk.Length/1MB,1)) Mo)" -ForegroundColor Green
    }
    if ($Cible -in 'tous', 'windows') {
        flet build windows --yes
        if ($LASTEXITCODE -ne 0) { throw 'échec de la construction Windows' }
        $zip = Join-Path $Releases "prise_commande-$version-windows.zip"
        # Tout le dossier : le .exe a besoin des DLL à côté de lui
        Compress-Archive -Path 'build\windows\*' -DestinationPath $zip -Force
        Write-Host "Windows : releases\prise_commande-$version-windows.zip" -ForegroundColor Green
    }
}
catch {
    Write-Host "`n*** $($_.Exception.Message) : faites une capture de cette fenêtre. ***" -ForegroundColor Red
    $echec = $true
}
finally {
    'FLET_ANDROID_SIGNING_KEY_STORE', 'FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD',
    'FLET_ANDROID_SIGNING_KEY_PASSWORD', 'FLET_ANDROID_SIGNING_KEY_ALIAS' |
        ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
    Pop-Location
}
if ($echec) { exit 1 }
if (-not $SansOuvrir) { explorer $Releases }
