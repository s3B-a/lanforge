<#
Opens the hub port to the local LAN only (Private/Domain profiles), so other
devices on your home network can reach it without exposing it publicly

Run as Administrator:
    powershell -ExecutionPolicy Bypass -File scripts\firewall_setup.ps1 -Port 8080
#>

param(
    [int]$Port = 8080
)

$ruleName = "LocalHub-Inbound-$Port"

if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "Firewall rule '$ruleName' already exists, removing old one first..."
    Remove-NetFirewallRule -DisplayName $ruleName
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $Port `
    -Profile Private,Domain `
    -Action Allow | Out-Null

Write-Host "Allowed inbound TCP $Port on Private/Domain network profiles."
Write-Host "Note: this does NOT open the port on Public networks (e.g. coffee shop Wi-Fi)."