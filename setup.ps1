<#
.SYNOPSIS
  One-shot setup for kicad-ai-template on Windows 10/11.

.DESCRIPTION
  1. Installs missing tools with winget: Git, Python 3.12, KiCad 10, GitHub CLI (and VS Code with -WithVSCode).
  2. Installs Claude Code (native installer) if the 'claude' command is missing.
  3. Puts kicad-cli on the user PATH.
  4. Fetches the kicad-sch-lint submodule.
  5. Installs Python packages: pymupdf, pymupdf4llm, openpyxl.
  6. Installs the Konnect KiCad plugin (KiCad must be closed).
  7. Writes .mcp.json for Claude Code with this machine's paths.
  8. Runs a health check.

  Safe to re-run. Every step skips what is already in place.

.EXAMPLE
  .\setup.cmd                      (same as: powershell -ExecutionPolicy Bypass -File setup.ps1)
  .\setup.cmd -CheckOnly           only report what is missing (writes only the .check\setup snapshot)
  .\setup.cmd -NoInstall           configure only, never install programs
  .\setup.cmd -SkipKonnect -WithVSCode
#>
param(
    [switch]$CheckOnly,
    [switch]$NoInstall,
    [switch]$SkipKonnect,
    [string]$KonnectVersion = 'latest',
    [switch]$WithVSCode
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$script:Problems = @()

function Say($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    ok    $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    warn  $msg" -ForegroundColor Yellow; $script:Problems += $msg }

function Update-SessionPath {
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$m;$u"
}

function Test-Command($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Get-PythonVersion {
    # The Microsoft Store 'python' stub exists but prints nothing useful. Ask for the real version.
    try {
        $v = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match '^\d+\.\d+$') { return [version]$v }
    } catch {}
    return $null
}

function Get-KicadCliVersion($exe) {
    try { $v = (& $exe version) | Select-Object -First 1; if ($v -match '^(\d+\.\d+)') { return [version]$Matches[1] } } catch {}
    return $null
}

function Find-KicadCli {
    # KiCad 10 only: older kicad-cli cannot read KiCad 10 files. Prefer the install folder over PATH.
    $cands = @(Get-ChildItem "$env:ProgramFiles\KiCad\10.*\bin\kicad-cli.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    $c = Get-Command kicad-cli -ErrorAction SilentlyContinue
    if ($c) { $cands += $c.Source }
    foreach ($exe in $cands) {
        $v = Get-KicadCliVersion $exe
        if ($v -and $v.Major -eq 10) { return $exe }
    }
    return $null
}

function Install-Winget($id, $label) {
    if ($CheckOnly -or $NoInstall) { Warn "$label missing (winget install --id $id)"; return }
    if (-not (Test-Command winget)) { Warn "$label missing and winget is not available. Install it by hand (see README)."; return }
    Say "Installing $label ($id)"
    & winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Warn "winget install $id failed (exit $LASTEXITCODE)" }
    Update-SessionPath
}

function Test-KicadRunning {
    # konnect: a running MCP server (Claude Code open) locks konnect.exe
    [bool](Get-Process -Name kicad, eeschema, pcbnew, konnect -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------- 1. programs
Say 'Programs'
Update-SessionPath

if (Test-Command git) { Ok "git $((git --version) -replace 'git version ','')" } else { Install-Winget 'Git.Git' 'Git for Windows' }

$py = Get-PythonVersion
if ($py -and $py -ge [version]'3.10') { Ok "python $py" }
else {
    if ($py) { Warn "python $py is older than 3.10" }
    Install-Winget 'Python.Python.3.12' 'Python 3.12'
    $py = Get-PythonVersion
    if ($py) { Ok "python $py" }
}

$cli = Find-KicadCli
if ($cli) { Ok "kicad-cli $(Get-KicadCliVersion $cli) ($cli)" }
else {
    $other = Get-Command kicad-cli -ErrorAction SilentlyContinue
    if ($other) { Warn "kicad-cli on PATH is not KiCad 10 ($($other.Source))" }
    Install-Winget 'KiCad.KiCad' 'KiCad 10'
    $cli = Find-KicadCli
    if ($cli) { Ok "kicad-cli $(Get-KicadCliVersion $cli) ($cli)" }
}

if (Test-Command gh) { Ok 'gh (GitHub CLI)' } else { Install-Winget 'GitHub.cli' 'GitHub CLI' }

if ($WithVSCode) {
    if (Test-Command code) { Ok 'VS Code' } else { Install-Winget 'Microsoft.VisualStudioCode' 'VS Code' }
    if ((Test-Command code) -and -not $CheckOnly) {
        & code --install-extension anthropic.claude-code --force | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok 'VS Code extension anthropic.claude-code' } else { Warn 'VS Code extension install failed' }
    }
}

# ---------------------------------------------------------------- 2. Claude Code
Say 'Claude Code'
$vscodeExt = (Test-Command code) -and ((& code --list-extensions) -contains 'anthropic.claude-code')
if (Test-Command claude) { Ok "claude $((claude --version) | Select-Object -First 1)" }
elseif ($vscodeExt) { Ok 'VS Code extension anthropic.claude-code (terminal CLI not installed, optional)' }
elseif ($CheckOnly -or $NoInstall) { Warn "claude missing (irm https://claude.ai/install.ps1 | iex)" }
else {
    # Child process: the installer may exit or change strict mode, which must not stop this script
    & powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) { Warn "Claude Code installer failed (exit $LASTEXITCODE). See https://code.claude.com/docs/en/setup" }
    Update-SessionPath
    $local = Join-Path $env:USERPROFILE '.local\bin'
    if (-not (Test-Command claude) -and (Test-Path (Join-Path $local 'claude.exe'))) { $env:Path += ";$local" }
    if (Test-Command claude) { Ok 'claude installed' } else { Warn 'claude installed but not on PATH yet. Open a new terminal.' }
}

# ---------------------------------------------------------------- 3. kicad-cli on PATH
Say 'kicad-cli on PATH'
$onPath = Get-Command kicad-cli -ErrorAction SilentlyContinue
if (-not $cli) { Warn 'KiCad 10 not found, cannot add kicad-cli to PATH' }
elseif ($onPath -and $onPath.Source -eq $cli) { Ok 'already on PATH' }
elseif ($CheckOnly) { Warn "KiCad 10 kicad-cli not first on PATH (add $(Split-Path $cli) to the user PATH)" }
else {
    $bin = Split-Path $cli
    # Edit the raw registry value so %VAR% entries stay unexpanded. KiCad 10 goes first.
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    $raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $parts = @($raw -split ';' | Where-Object { $_ -and ($_.TrimEnd('\') -ne $bin.TrimEnd('\')) })
    $key.SetValue('Path', ((@($bin) + $parts) -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
    $key.Close()
    # Setting any user variable broadcasts WM_SETTINGCHANGE, so new terminals see the new PATH
    [Environment]::SetEnvironmentVariable('KICAD_AI_TEMPLATE_SETUP', '1', 'User')
    [Environment]::SetEnvironmentVariable('KICAD_AI_TEMPLATE_SETUP', $null, 'User')
    $env:Path = "$bin;$env:Path"
    Ok "added $bin to the front of the user PATH (new terminals pick it up)"
}

# ---------------------------------------------------------------- 4. submodule
Say 'kicad-sch-lint submodule'
$kschlint = Join-Path $Root 'tools\kicad-sch-lint\kschlint'
if (Test-Path $kschlint) { Ok 'present' }
elseif ($CheckOnly) { Warn 'submodule missing (git submodule update --init)' }
elseif (Test-Command git) {
    & git -C $Root -c core.longpaths=true submodule update --init --recursive
    if (Test-Path $kschlint) { Ok 'fetched' } else { Warn 'git submodule update failed' }
} else { Warn 'git missing, submodule not fetched' }

# ---------------------------------------------------------------- 5. python packages
Say 'Python packages'
if (Get-PythonVersion) {
    $missing = @((& python -c "import importlib.util as u; print(' '.join(m for m in ('pymupdf', 'pymupdf4llm', 'openpyxl') if not u.find_spec(m)))") -split ' ' | Where-Object { $_ })
    if (-not $missing) { Ok 'pymupdf, pymupdf4llm, openpyxl' }
    elseif ($CheckOnly) { Warn "missing: $($missing -join ', ') (python -m pip install --user $($missing -join ' '))" }
    else {
        $inVenv = (& python -c "import sys; print(sys.prefix != sys.base_prefix)") -eq 'True'
        $pipArgs = @('-m', 'pip', 'install', '--upgrade')
        if (-not $inVenv) { $pipArgs += '--user' }
        & python @($pipArgs + $missing)
        if ($LASTEXITCODE -eq 0) { Ok "installed $($missing -join ', ')" } else { Warn 'pip install failed' }
    }
} else { Warn 'python missing, skipped' }

# ---------------------------------------------------------------- 6. Konnect
Say 'Konnect KiCad plugin'
$helpers = Join-Path $Root 'tools\setup_helpers.py'
if ($SkipKonnect) { Ok 'skipped (-SkipKonnect)' }
elseif (-not (Get-PythonVersion)) { Warn 'python missing, skipped' }
else {
    $exe = & python $helpers konnect-exe
    $have = ($LASTEXITCODE -eq 0)
    if ($CheckOnly) { if ($have) { Ok $exe } else { Warn 'Konnect not installed' } }
    elseif ($have -and $KonnectVersion -eq 'latest' -and (Test-KicadRunning)) { Ok "$exe (KiCad or Konnect running, update check skipped)" }
    elseif ($NoInstall -and -not $have) { Warn 'Konnect not installed (-NoInstall)' }
    elseif (Test-KicadRunning) { Warn 'KiCad or a Konnect server (Claude Code) is running. Close them and re-run setup to install Konnect.' }
    else {
        & python $helpers konnect --version $KonnectVersion
        if ($LASTEXITCODE -ne 0) { Warn 'Konnect install failed. Manual install: see README, section Konnect.' }
    }
}

# ---------------------------------------------------------------- 7. .mcp.json
Say 'MCP config (.mcp.json)'
if ($CheckOnly) {
    if (Test-Path (Join-Path $Root '.mcp.json')) { Ok 'present' } else { Warn '.mcp.json missing (run setup without -CheckOnly)' }
} elseif (Get-PythonVersion) {
    & python $helpers mcp
} else { Warn 'python missing, skipped' }

# ---------------------------------------------------------------- 8. health check
Say 'Health check'
if ((Get-PythonVersion) -and (Test-Path $kschlint) -and (Find-KicadCli)) {
    Push-Location $Root
    try {
        & python tools\sch_check.py snapshot setup | Out-Host
        if ($LASTEXITCODE -eq 0) { Ok 'kicad-cli netlist, ERC and BOM export' } else { Warn 'sch_check snapshot failed' }
        $env:PYTHONPATH = Join-Path $Root 'tools\kicad-sch-lint'
        & python -m kschlint lint kicad | Out-Host
        if ($LASTEXITCODE -eq 0) { Ok 'kschlint lint' } else { Warn 'kschlint lint reported errors' }
    } finally { Pop-Location }
} else { Warn 'health check skipped (python, submodule or kicad-cli missing)' }

Write-Host ''
if ($script:Problems.Count -eq 0) {
    Write-Host 'All set. Open a NEW terminal in this folder and run: claude' -ForegroundColor Green
    Write-Host 'Type /mcp in Claude Code to check that konnect and kschlint are connected.' -ForegroundColor Green
} else {
    Write-Host "$($script:Problems.Count) problem(s):" -ForegroundColor Yellow
    $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    exit 1
}
