param(
    [int]$Port = 8765,
    [string]$HostAddress = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
& $Python -m wenling_lan_host --host $HostAddress --port $Port --data-dir (Join-Path $Root "data")
