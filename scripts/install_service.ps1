<#
Registers the hub as a background Windows service using NSSM, so it starts
on boot and keeps running after you log out.

One-time setup:
  1. Download NSSM from https://nssm.cc/download and extract nssm.exe to
     .\nssm\nssm.exe (nssm/ is gitignored on purpose)
  2. Create the venv and install deps:
       python -m venv .venv
       .venv\Scripts\pip install -r backend\requirements.txt
  3. Copy cfg\.env.example to cfg\.env and set a real HUB_TOKEN

Then run as Administrator:
    powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1
#>

param(
    [string]$ServiceName = "LocalHub"
)

$root = (Resolve-Path "$PSScriptRoot\..").Path
$nssm = Join-Path $root "nssm\nssm.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"
$mainScript = Join-Path $root "backend\app\main.py"

if (-not (Test-Path $nssm)) {
    Write-Error "nssm.exe not found at $nssm. Download it from https://nssm.cc/download first."
    exit 1
}
if (-not (Test-Path $python)) {
    Write-Error "$python not found. Run: python -m venv .venv; .venv\Scripts\pip install -r backend\requirements.txt"
    exit 1
}

& $nssm install $ServiceName $python $mainScript
& $nssm set $ServiceName AppDirectory $root
& $nssm set $ServiceName DisplayName "Local Home Server Hub"
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppStdout (Join-Path $root "logs\hub.out.log")
& $nssm set $ServiceName AppStderr (Join-Path $root "logs\hub.err.log")

New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null

Write-Host "Service '$ServiceName' installed. Start it with:"
Write-Host "    Start-Service $ServiceName"
Write-Host "Or manage it via services.msc / nssm.exe (start|stop|restart|remove) $ServiceName"