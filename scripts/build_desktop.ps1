param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$arguments = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "耳廓工程分析",
    "--add-data", "desktop_app\assets;desktop_app\assets",
    "--collect-all", "pyvista",
    "--collect-all", "pyvistaqt",
    "--collect-all", "vtkmodules",
    "desktop_app\__main__.py"
)
if ($OneFile) { $arguments += "--onefile" }

& python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败，退出码：$LASTEXITCODE" }

Write-Host "构建完成：dist\耳廓工程分析"
