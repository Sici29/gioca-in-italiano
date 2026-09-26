<#
    Compila GiocaInItaliano.exe in un unico file.
    Uso:  .\build\build.ps1  [-SaltaTest]
#>
param([switch]$SaltaTest)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = $root

Write-Host "Cartella progetto: $root" -ForegroundColor DarkGray

# L'anteprima di sviluppo non deve finire nell'eseguibile.
Remove-Item (Join-Path $root "hub\web\_preview.html") -Force -ErrorAction SilentlyContinue

Write-Host "`n[1/5] Dipendenze..." -ForegroundColor Cyan
python -m pip install -r requirements.txt --quiet
python -m pip install pyinstaller --quiet

if (-not $SaltaTest) {
    Write-Host "[2/5] Test..." -ForegroundColor Cyan
    python -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nTest falliti: compilazione interrotta." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[2/5] Test saltati." -ForegroundColor DarkGray
}

Write-Host "[3/5] Icona e proprieta' del file..." -ForegroundColor Cyan
python tools/make_icon.py build/icon.ico
python tools/make_version_info.py build/version_info.txt

Write-Host "[4/5] Compilazione..." -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath "$root\dist" `
    --workpath "$root\build\work" `
    "$root\build\GiocaInItaliano.spec"

$exe = Join-Path $root "dist\GiocaInItaliano.exe"
if (-not (Test-Path $exe)) {
    Write-Host "`nCompilazione fallita: eseguibile non trovato." -ForegroundColor Red
    exit 1
}

Remove-Item (Join-Path $root "build\work") -Recurse -Force -ErrorAction SilentlyContinue

# PyInstaller impacchetta quello che trova installato, non quello che serve:
# un PyQt5 comparso nel Python di sviluppo e' finito dentro l'exe senza un
# avviso, con la sua licenza GPL. Qui la build si ferma prima che succeda.
python tools/controlla_exe.py $exe
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nL'eseguibile contiene librerie che non devono esserci: non distribuirlo." -ForegroundColor Red
    exit 1
}

$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "[5/5] Fatto." -ForegroundColor Green
Write-Host "`n  $exe  ($mb MB)`n" -ForegroundColor White
