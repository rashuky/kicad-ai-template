<#
.SYNOPSIS
  Rename the KiCad project in kicad/ (Project.kicad_* -> <Name>.kicad_*). Run once, right after creating a repo from the template.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\rename_project.ps1 -Name MyBoard
#>
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Name,
    [string]$Dir = ''
)
$ErrorActionPreference = 'Stop'
# $PSScriptRoot is empty inside param defaults on Windows PowerShell 5.1
if (-not $Dir) { $Dir = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\kicad' }
$Dir = (Resolve-Path $Dir).Path

if (Get-ChildItem $Dir -Filter '*.lck' -ErrorAction SilentlyContinue) { throw "KiCad has this project open (.lck files in $Dir). Close KiCad first." }
$pro = @(Get-ChildItem $Dir -Filter '*.kicad_pro')
if ($pro.Count -ne 1) { throw "Expected one .kicad_pro in $Dir, found $($pro.Count)." }
$old = $pro[0].BaseName
if ($old -eq $Name) { Write-Host "Already named $Name."; exit 0 }

$enc = New-Object System.Text.UTF8Encoding($false)
function Edit-Text($path, [scriptblock]$change) {
    $t = [IO.File]::ReadAllText($path, $enc)
    [IO.File]::WriteAllText($path, (& $change $t), $enc)
}

$q = [regex]::Escape($old)
# .kicad_pro: meta.filename
Edit-Text "$Dir\$old.kicad_pro" { param($t) $t -replace "`"$q\.kicad_pro`"", "`"$Name.kicad_pro`"" }
# schematics: symbol instance project names, root title if still the old name
foreach ($s in Get-ChildItem $Dir -Filter '*.kicad_sch') {
    Edit-Text $s.FullName { param($t) ($t -replace "\(project `"$q`"", "(project `"$Name`"") -replace "\(title `"$q`"\)", "(title `"$Name`")" }
}
foreach ($ext in 'kicad_pro', 'kicad_sch', 'kicad_pcb', 'kicad_prl') {
    $f = Join-Path $Dir "$old.$ext"
    if (Test-Path $f) { Rename-Item $f "$Name.$ext" }
}
Write-Host "Renamed $old -> $Name in $Dir"
