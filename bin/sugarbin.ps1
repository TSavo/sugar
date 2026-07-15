param(
    [ValidateSet('debug', 'release')]
    [string]$Profile = 'release'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$rustRoot = Join-Path $root 'implementations\rust'

if ($env:SUGAR_BIN) {
    $explicit = [System.IO.Path]::GetFullPath($env:SUGAR_BIN)
    if (-not (Test-Path -LiteralPath $explicit -PathType Leaf)) {
        throw "sugarbin: SUGAR_BIN does not exist: $explicit"
    }
    Write-Output $explicit
    exit 0
}

$cargo = if ($env:CARGO) {
    $env:CARGO
} elseif (Get-Command cargo.exe -ErrorAction SilentlyContinue) {
    (Get-Command cargo.exe).Source
} else {
    Join-Path $HOME '.cargo\bin\cargo.exe'
}

if (-not (Test-Path -LiteralPath $cargo -PathType Leaf)) {
    throw "sugarbin: cargo.exe is required for a native Windows build"
}

$arguments = @('build', '--package', 'sugar-cli', '--bin', 'sugar')
if ($Profile -eq 'release') {
    $arguments += '--release'
}
& $cargo @arguments --manifest-path (Join-Path $rustRoot 'Cargo.toml')
if ($LASTEXITCODE -ne 0) {
    throw "sugarbin: native Windows build failed with exit $LASTEXITCODE"
}

$targetRoot = if ($env:CARGO_TARGET_DIR) {
    [System.IO.Path]::GetFullPath($env:CARGO_TARGET_DIR)
} else {
    Join-Path $rustRoot 'target'
}
$binary = Join-Path $targetRoot "$Profile\sugar.exe"
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
    throw "sugarbin: build succeeded without expected binary: $binary"
}
Write-Output ([System.IO.Path]::GetFullPath($binary))
