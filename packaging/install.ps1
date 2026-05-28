## Transcript Knowledge Base - Windows Installer
## Run with: powershell -ExecutionPolicy Bypass -File packaging\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Transcript Knowledge Base - Installer ===" -ForegroundColor Cyan
Write-Host ""

# Check/install uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python package manager)..."
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = "$env:LOCALAPPDATA\uv;$env:Path"
    Write-Host ""
}

Write-Host "uv version: $(uv --version)"

# Get project directory (parent of packaging/)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

Write-Host "Project directory: $ProjectDir"
Write-Host ""

# Install dependencies
Write-Host "Installing dependencies (this may take a few minutes on first run)..."
Push-Location $ProjectDir
uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
Write-Host ""

# Verify
Write-Host "Verifying installation..."
uv run python -c "import chromadb, sentence_transformers, mcp; print('All packages OK')"
if ($LASTEXITCODE -ne 0) { throw "Package verification failed" }
Write-Host ""

# Check data
$DataDir = Join-Path $ProjectDir "data"
$DbPath = Join-Path $DataDir "transcripts.db"
if (Test-Path $DbPath) {
    Write-Host "=== Corpus Stats ===" -ForegroundColor Cyan
    uv run transcripts stats
    Write-Host ""
} else {
    Write-Host "WARNING: No database found. Run: uv run transcripts ingest" -ForegroundColor Yellow
    Write-Host ""
}

# Claude Desktop config
$ClaudeConfigDir = Join-Path $env:APPDATA "Claude"
$ClaudeConfigFile = Join-Path $ClaudeConfigDir "claude_desktop_config.json"

Write-Host "=== Claude Desktop Configuration ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Add this to: $ClaudeConfigFile"
Write-Host "Merge into the mcpServers section:"
Write-Host ""

$ProjectDirEscaped = $ProjectDir -replace '\\', '\\\\'
$DataDirEscaped = $DataDir -replace '\\', '\\\\'

Write-Host @"
    "transcripts": {
      "command": "uv",
      "args": ["--directory", "$ProjectDirEscaped", "run", "python", "-m", "transcripts.mcp_server"],
      "env": {
        "TRANSCRIPTS_DATA_DIR": "$DataDirEscaped"
      }
    }
"@

Write-Host ""
Write-Host "After adding the config:" -ForegroundColor Green
Write-Host "  1. Fully close Claude Desktop (right-click tray icon > Quit)"
Write-Host "  2. Reopen Claude Desktop"
Write-Host "  3. Look for the hammer/tools icon in the chat input"
Write-Host '  4. Ask: "What are the major themes in the transcripts?"'
Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Cyan

Pop-Location
