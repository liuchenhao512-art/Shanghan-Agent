$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))) {
    throw '开发环境尚未安装，请按 README.md 初始化。普通使用请运行 dist 中的安装包。'
}
& (Join-Path $PSScriptRoot 'node_modules\.bin\electron.cmd') $PSScriptRoot
