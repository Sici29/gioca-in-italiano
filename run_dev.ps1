# Avvia l'hub dai sorgenti, senza compilare l'eseguibile.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python -m hub --debug
